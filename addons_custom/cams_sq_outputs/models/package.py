import csv
import hashlib
import io
import re
from odoo import models, _
from odoo.exceptions import AccessError, UserError
from odoo.addons.cams_sq.models.package import csv_value
from .output import NATIVE_REPORTS


def safe_name(value):
    return re.sub(r'[^\w .()-]', '_', value or '').strip('. ')[:100] or 'document'


class Package(models.Model):
    _inherit = 'iatf.audit'

    def _sq_package_outputs(self, archive, remaining_bytes):
        super()._sq_package_outputs(archive, remaining_bytes)
        self.ensure_one()
        self.check_access('read')
        requirements = self.sq_line_ids.item_id.requirement_ids.sorted(lambda r: (r.output_sequence, r.source_key))
        requirements.check_access('read')
        manifest, missing = [], []
        used = 0

        def add(path, content):
            nonlocal used
            if used + len(content) > remaining_bytes:
                raise UserError(_('서류 포함 ZIP이 100MB를 넘습니다. 기간/평가 범위를 나누십시오.'))
            archive.writestr(path, content)
            used += len(content)
            return hashlib.sha256(content).hexdigest()

        for req in requirements:
            if req.company_id != self.company_id:
                raise AccessError(_('다른 회사의 준비서류입니다.'))
            codes = sorted((req.item_ids & self.sq_standard_id.item_ids).mapped('code'))
            folder = (codes[0].split('_')[0] if codes else '미분류')
            prefix = safe_name('_'.join(codes)) + '_' + safe_name(req.source_key) + '_' + safe_name(req.name)
            base = folder + '/' + prefix
            row = [req.output_sequence, req.source_key, ' '.join(codes), req.name, req.output_type or '', '', '', '']
            try:
                wizard = self.env['sq.output.wizard'].create({'requirement_ids': [(6, 0, req.ids)],
                    'date_from': self.sq_date_from, 'date_to': self.sq_date_to})
                payload = wizard._payloads()[0]
                if payload['warning']:
                    row[7] = payload['warning']
                    missing.append([req.source_key, req.name, payload['warning']])
                if payload['rows']:
                    if req.output_format == 'xlsx' or req.output_type == 'export':
                        raw = wizard._xlsx(); path = base + '.xlsx'
                    else:
                        raw, unused = self.env['ir.actions.report']._render_qweb_pdf('cams_sq_outputs.report_output', res_ids=wizard.ids)
                        path = base + '.pdf'
                    row[5] = path; row[6] = add(path, raw)
                    native_id = NATIVE_REPORTS.get(req.output_model)
                    if native_id:
                        if self.env.ref(native_id, raise_if_not_found=False):
                            action, records = wizard._native_report()
                            content, unused = self.env['ir.actions.report'].with_company(self.company_id)._render_qweb_pdf(action, res_ids=records.ids)
                            native_path = base + '_기존전용서식.pdf'
                            digest = add(native_path, content)
                            manifest.append(row[:5] + [native_path, digest, '기존 전용 리포트 재사용'])
                        else:
                            missing.append([req.source_key, req.name, '기존 전용 리포트 미설치: 공용 원천 출력만 수록'])
                    seen = set()
                    for source in payload['rows']:
                        for attachment in self.env['ir.attachment'].browse(source['file_ids']):
                            if attachment.id in seen:
                                continue
                            seen.add(attachment.id)
                            attachment.check_access('read')
                            if attachment.company_id and attachment.company_id != self.company_id:
                                raise AccessError(_('다른 회사의 원천 첨부입니다.'))
                            if attachment.type != 'binary':
                                missing.append([req.source_key, req.name, '원천 첨부는 외부 링크']); continue
                            if attachment.file_size > 25 * 1024**2:
                                raise UserError(_('원천 첨부가 25MB를 넘습니다.'))
                            content = attachment.raw or b''
                            if len(content) > 25 * 1024**2:
                                raise UserError(_('원천 첨부가 25MB를 넘습니다.'))
                            file_path = base + '/%d_%s' % (attachment.id, safe_name(attachment.name))
                            digest = add(file_path, content)
                            manifest.append(row[:5] + [file_path, digest, '출력 시점 원천 첨부'])
                elif payload['documents']:
                    files = 0
                    for info in payload['documents']:
                        doc = self.env['iatf.document'].browse(info['id'])
                        doc.check_access('read')
                        for attachment in doc.attachment_ids:
                            attachment.check_access('read')
                            if attachment.company_id and attachment.company_id != self.company_id:
                                raise AccessError(_('다른 회사의 첨부입니다.'))
                            if attachment.type != 'binary':
                                missing.append([req.source_key, req.name, '외부 링크: 파일 미수집']); continue
                            if attachment.file_size > 25 * 1024**2:
                                raise UserError(_('첨부 파일이 25MB를 넘습니다.'))
                            path = base + '/%d_%s' % (attachment.id, safe_name(attachment.name))
                            raw = attachment.raw or b''
                            if len(raw) > 25 * 1024**2:
                                raise UserError(_('첨부 파일이 25MB를 넘습니다.'))
                            add(path, raw); files += 1
                            manifest.append(row[:5] + [path, hashlib.sha256(raw).hexdigest(), row[7]])
                    if not files:
                        row[7] = '연결 문서에 출력 가능한 첨부 없음'
                        missing.append([req.source_key, req.name, row[7]])
                if not row[5] and not row[7] and not payload['documents']:
                    row[7] = '실제 출력 원천 미연결'
                    missing.append([req.source_key, req.name, row[7]])
            except AccessError:
                row[7] = '원천 조회 권한/회사 범위 제한'
                missing.append([req.source_key, req.name, row[7]])
            manifest.append(row)
        for path, headings, rows in [
            ('00_목차.csv', ['순서', '원본행키', '항목', '서류명', '출력유형', '파일', 'SHA256', '미비/참고'], manifest),
            ('99_미비/미비목록.csv', ['원본행키', '서류명', '사유'], missing)]:
            stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(headings)
            writer.writerows([[csv_value(value) for value in row] for row in rows])
            add(path, stream.getvalue().encode('utf-8-sig'))
