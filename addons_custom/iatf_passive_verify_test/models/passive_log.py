"""Transactional observation; never retry a stock/financial core operation."""
import base64
import hashlib
import inspect
from pathlib import Path
import traceback

import psycopg2

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, AccessDenied, UserError


_LOG_TOKEN = object()


class _Observed(Exception):
    """Roll back a successful quarantine proposal without applying it."""


class ResCompany(models.Model):
    _inherit = 'res.company'

    iatf_passive_enabled = fields.Boolean(
        string='IATF 업무 차단 패스', default=True,
        help='검증 실패를 로그로 남기고 업무를 계속합니다. 검사/승인 결과는 변경하지 않습니다.')

    def write(self, vals):
        if 'iatf_passive_enabled' in vals:
            if not self.env.user.has_group('base.group_system'):
                raise AccessError(_('IATF 패스 설정은 시스템 관리자만 변경할 수 있습니다.'))
            self.check_access('write')
            for company in self:
                if company.iatf_passive_enabled != bool(vals['iatf_passive_enabled']):
                    self.env['iatf.passive.log']._record(
                        company, '설정', '회사별 패스 모드 변경',
                        'enabled=%s -> %s' % (company.iatf_passive_enabled, bool(vals['iatf_passive_enabled'])),
                        ResCompany.write, outcome='configuration')
        return super().write(vals)


class PassiveSource(models.Model):
    _name = 'iatf.passive.source'
    _description = 'IATF 통과 당시 원본 소스 파일'
    _rec_name = 'path'
    _order = 'id desc'

    path = fields.Char(required=True, readonly=True)
    sha256 = fields.Char(required=True, readonly=True, index=True)
    filename = fields.Char(required=True, readonly=True)
    content = fields.Binary(required=True, readonly=True, attachment=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_iatf_passive_log_token') is not _LOG_TOKEN:
            raise AccessError(_('소스 스냅샷은 패스 서비스만 생성합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('통과 당시 원본 소스는 수정할 수 없습니다.'))

    @api.ondelete(at_uninstall=False)
    def _protect_source(self):
        raise AccessError(_('통과 당시 원본 소스는 삭제할 수 없습니다.'))


class PassiveLog(models.Model):
    _name = 'iatf.passive.log'
    _description = 'IATF 패스 검증 로그'
    _order = 'passed_at desc, id desc'
    _rec_name = 'point'

    passed_at = fields.Datetime(string='통과 일시', required=True, readonly=True, default=fields.Datetime.now, index=True)
    company_id = fields.Many2one('res.company', string='회사', required=True, readonly=True, index=True)
    user_id = fields.Many2one('res.users', string='실행자', required=True, readonly=True)
    area = fields.Char(string='분야', required=True, readonly=True, index=True)
    description = fields.Text(string='내용', readonly=True)
    error_message = fields.Text(string='오류 메시지', readonly=True)
    error_type = fields.Char(string='오류 유형', readonly=True)
    point = fields.Char(string='지점', required=True, readonly=True, index=True)
    outcome = fields.Selection([
        ('bypassed', '검증 실패 통과'), ('observed', '검사대기 이동 미적용'),
        ('auxiliary', '자동 후처리 실패 통과'), ('configuration', '설정 변경'),
    ], string='처리', required=True, readonly=True)
    res_model = fields.Char(string='원본 모델', required=True, readonly=True, index=True)
    res_id = fields.Integer(string='원본 레코드 ID', readonly=True, index=True)
    record_name = fields.Char(string='원본 이름 스냅샷', readonly=True)
    source_id = fields.Many2one('iatf.passive.source', string='원본 파일', readonly=True, ondelete='restrict')
    source_line = fields.Integer(string='원본 줄 번호', readonly=True)
    traceback_text = fields.Text(string='호출 경로', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_iatf_passive_log_token') is not _LOG_TOKEN:
            raise AccessError(_('패스 로그는 서비스만 생성합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('패스 로그는 수정할 수 없습니다.'))

    @api.ondelete(at_uninstall=False)
    def _protect_log(self):
        raise AccessError(_('패스 로그는 삭제할 수 없습니다.'))

    @api.model
    def _enabled(self, records):
        companies = records.company_id if 'company_id' in records._fields else self.env.company
        companies = companies or self.env.company
        if not self.env.su and any(company not in self.env.companies for company in companies):
            raise AccessError(_('허용된 회사의 업무만 처리할 수 있습니다.'))
        # Read only the mode with sudo; the business callback retains its actor.
        return all(companies.sudo().mapped('iatf_passive_enabled'))

    @api.model
    def _run(self, records, callback, area, description, *, mode='gate', fallback=True,
             args=(), kwargs=None, allow_quality_access=False):
        kwargs = kwargs or {}
        if not self._enabled(records):
            return callback(*args, **kwargs)
        # An unrelated pending ORM error must not be attributed to this callback.
        self.env.flush_all()
        error = None
        try:
            with self.env.cr.savepoint():
                result = callback(*args, **kwargs)
                if mode == 'observe':
                    raise _Observed()
                return result
        except _Observed:
            pass
        except (AccessDenied, psycopg2.Error):
            # Concurrency retry, SQL integrity and authentication remain native.
            raise
        except AccessError as exc:
            # Only isolated automatic IATF side effects can fail for quality ACLs.
            # Stock/MRP/BOM core calls are deliberately outside these callbacks.
            if mode != 'auxiliary' and not allow_quality_access:
                raise
            error = exc
        except UserError as exc:
            error = exc
        except Exception as exc:
            error = exc
        self._record(records, area, description, str(error) if error else
                     _('검사대기 위치로 전환할 수 있지만 패스 모드이므로 원래 입고 위치를 유지합니다.'),
                     callback, error=error,
                     outcome={'gate': 'bypassed', 'observe': 'observed', 'auxiliary': 'auxiliary'}[mode])
        return fallback

    @api.model
    def _record(self, records, area, description, message, callback, *, error=None, outcome='bypassed', caller_line=None):
        function = inspect.unwrap(getattr(callback, '__func__', callback))
        code = function if inspect.iscode(function) else getattr(function, '__code__', None)
        path = inspect.getsourcefile(function)
        line = caller_line or getattr(code, 'co_firstlineno', 0)
        frames = traceback.extract_tb(error.__traceback__) if error else []
        # Prefer the actual IATF raise site, not the generic interceptor.
        for frame in reversed(frames):
            if '/iatf_' in frame.filename.replace('\\', '/') and 'iatf_passive_verify_test' not in frame.filename:
                path, line = frame.filename, frame.lineno
                break
        source = self.env['iatf.passive.source']
        if path:
            file = Path(path)
            parts = file.parts
            index = next((i for i, part in enumerate(parts)
                          if part.startswith('iatf_') or part in (
                              'engel_injection', 'injection_worksite', 'gh_total_mes', 'escon_br_intake')), None)
            if index is not None and file.suffix == '.py':
                relative = '/'.join(parts[index:])
                data = file.read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                Source = source.sudo().with_context(_iatf_passive_log_token=_LOG_TOKEN)
                source = Source.search([('path', '=', relative), ('sha256', '=', digest)], limit=1)
                if not source:
                    source = Source.create({'path': relative, 'sha256': digest, 'filename': file.name,
                                            'content': base64.b64encode(data)})
        point = '%s.%s' % (getattr(function, '__module__', records._name),
                           getattr(function, '__qualname__', getattr(code, 'co_name', str(function))))
        vals_list = []
        for record in records or [None]:
            company = (record.company_id if record is not None and 'company_id' in record._fields else self.env.company)
            if record is not None and record._name == 'res.company':
                company = record
            company = company or self.env.company
            vals_list.append({
                'company_id': company.id, 'user_id': self.env.uid, 'area': area,
                'description': description, 'error_message': message, 'error_type': type(error).__name__ if error else False,
                'point': point, 'outcome': outcome, 'res_model': records._name,
                'res_id': record.id if record is not None else 0,
                'record_name': record.display_name if record is not None else False,
                'source_id': source.id or False, 'source_line': line,
                'traceback_text': ''.join(traceback.format_list(frames)),
            })
        # Failure to persist evidence aborts the operation; no silent unlogged pass.
        return self.sudo().with_context(_iatf_passive_log_token=_LOG_TOKEN).create(vals_list)

    def action_open_record(self):
        self.ensure_one()
        self.check_access('read')
        if self.res_model not in self.env or not self.res_id:
            raise UserError(_('원본 레코드를 찾을 수 없습니다.'))
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            raise UserError(_('원본이 삭제되었습니다. 로그의 모델·ID·이름 스냅샷을 확인하세요.'))
        record.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': record._name, 'res_id': record.id,
                'view_mode': 'form', 'target': 'current'}

    def action_open_attachments(self):
        self.ensure_one()
        self.action_open_record()  # Reuse the original record ACL check.
        return {'type': 'ir.actions.act_window', 'res_model': 'ir.attachment', 'view_mode': 'list,form',
                'domain': [('res_model', '=', self.res_model), ('res_id', '=', self.res_id)],
                'name': _('원본 레코드 첨부파일')}


class Attachment(models.Model):
    _inherit = 'ir.attachment'

    def _check_passive_source_change(self):
        if self.sudo().filtered(lambda record: record.res_model in ('iatf.passive.source', 'iatf.passive.log')):
            raise AccessError(_('패스 로그의 원본 파일 스냅샷은 변경하거나 삭제할 수 없습니다.'))

    def write(self, vals):
        if {'datas', 'raw', 'db_datas', 'store_fname', 'name', 'mimetype', 'type',
                'url', 'res_model', 'res_id', 'res_field', 'public', 'access_token', 'company_id'} & vals.keys():
            self._check_passive_source_change()
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _protect_passive_attachment(self):
        self._check_passive_source_change()
