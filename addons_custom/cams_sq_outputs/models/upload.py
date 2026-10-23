import base64
import hashlib
import io
import stat
import zipfile
from pathlib import PurePosixPath
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_TOKEN = object()
MAX_FILE = 25 * 1024**2
MAX_TOTAL = 100 * 1024**2


class Document(models.Model):
    _inherit = 'iatf.document'
    sq_upload_key = fields.Char('SQ 원본 업로드 지문', readonly=True, copy=False, index=True)
    _sql_constraints = [('sq_upload_unique', 'unique(company_id,sq_upload_key)', '같은 SQ 업로드 파일이 이미 연결되어 있습니다.')]

    @api.model_create_multi
    def create(self, values):
        if any(row.get('sq_upload_key') for row in values) and self.env.context.get('_sq_upload') is not _TOKEN:
            raise AccessError(_('업로드 지문은 일괄 업로드 도구에서만 설정합니다.'))
        return super().create(values)

    def write(self, values):
        if 'sq_upload_key' in values:
            raise AccessError(_('업로드 원본 지문은 변경할 수 없습니다. 새 파일을 등록하십시오.'))
        return super().write(values)


class Upload(models.TransientModel):
    _name = 'sq.output.upload'
    _description = 'SQ 문서 폴더 일괄 업로드'
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    category_id = fields.Many2one('iatf.document.category', string='문서 분류', required=True)
    archive = fields.Binary('서류 폴더 ZIP', required=True, attachment=False)
    filename = fields.Char()
    result = fields.Text('처리 결과', readonly=True)

    def action_import(self):
        self.ensure_one()
        self.check_access('write')
        if not self.env.user.has_group('cams_sq_outputs.group_sq_uploader') and not self.env.su:
            raise AccessError(_('SQ 서류 업로드 담당 권한이 필요합니다. 문서 담당자에게 요청하십시오.'))
        if self.company_id not in self.env.companies:
            raise AccessError(_('허용된 회사만 선택하십시오.'))
        self.category_id.check_access('read')
        self.env['iatf.document'].check_access('create')
        if not self.archive or len(self.archive) > MAX_TOTAL * 4 // 3 + 8:
            raise UserError(_('ZIP 파일은 100MB 이하로 올리십시오.'))
        try:
            raw = base64.b64decode(self.archive, validate=True)
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except (ValueError, zipfile.BadZipFile) as error:
            raise UserError(_('정상 ZIP 파일을 선택하십시오.')) from error
        with archive, self.env.cr.savepoint():
            infos = [entry for entry in archive.infolist() if not entry.is_dir()]
            if not infos or len(infos) > 500 or sum(entry.file_size for entry in infos) > MAX_TOTAL:
                raise UserError(_('압축 해제 크기 100MB·파일 500개 이하만 가능합니다.'))
            prepared, names = [], set()
            for info in infos:
                path = PurePosixPath(info.filename)
                if (len(path.parts) != 2 or path.is_absolute() or str(path) != info.filename or any(part in ('.', '..') for part in path.parts)
                        or '\\' in info.filename or ':' in info.filename or '\x00' in info.filename
                        or any(ord(char) < 32 for char in info.filename) or len(path.name) > 180
                        or stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1
                        or info.file_size > MAX_FILE or info.filename in names):
                    raise UserError(_('파일은 원본행키/파일명 형식이어야 하며 링크·중복·암호화 파일은 허용하지 않습니다: %s') % info.filename)
                names.add(info.filename)
                req = self.env['sq.doc.requirement'].search([('company_id', '=', self.company_id.id),
                    ('source_key', '=', path.parts[0]), ('output_type', '=', 'upload')])
                if len(req) != 1:
                    raise UserError(_('업로드 유형 서류의 원본 행 키를 찾지 못했습니다: %s') % path.parts[0])
                req.check_access('write')
                try:
                    content = archive.read(info)
                except (RuntimeError, zipfile.BadZipFile) as error:
                    raise UserError(_('압축 파일 내용을 확인하십시오.')) from error
                if len(content) != info.file_size:
                    raise UserError(_('압축 파일 크기가 일치하지 않습니다.'))
                digest = hashlib.sha256((req.source_key + '\0' + path.name + '\0').encode() + content).hexdigest()
                prepared.append((req, path.name, content, digest))
            # Serialize same-company imports; failure rolls back the entire upload.
            self.env.cr.execute('SELECT id FROM res_company WHERE id=%s FOR UPDATE', [self.company_id.id])
            result = []
            Document = self.env['iatf.document'].with_context(active_test=False)
            for req, name, content, digest in prepared:
                document = Document.search([('company_id', '=', self.company_id.id), ('sq_upload_key', '=', digest)])
                created = not document
                if created:
                    document = Document.with_context(_sq_upload=_TOKEN).create({
                        'name': req.name + ' / ' + name, 'company_id': self.company_id.id,
                        'category_id': self.category_id.id, 'doc_type': 'record', 'sq_upload_key': digest,
                        'external_origin': 'SQ ' + req.source_key})
                    attachment = self.env['ir.attachment'].create({'name': name, 'raw': content,
                        'res_model': document._name, 'res_id': document.id, 'company_id': self.company_id.id})
                    document.write({'attachment_ids': [(4, attachment.id)]})
                else:
                    document.check_access('read')
                    document.attachment_ids.check_access('read')
                    matches = document.attachment_ids.filtered(lambda attachment: attachment.name == name and attachment.type == 'binary')
                    if not any(attachment.raw == content for attachment in matches):
                        raise UserError(_('기존 업로드 문서의 파일이 바뀌었습니다. 원본/개정 이력을 확인하십시오: %s') % document.doc_number)
                req.write({'document_ids': [(4, document.id)]})
                result.append('%s / %s / %s / %s' % (req.source_key, name, document.doc_number,
                    '새 초안' if created else '기존 연결 유지'))
            self.write({'result': '\n'.join(result) + '\n문서 승인과 준비 확인은 자동 변경하지 않았습니다.'})
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}
