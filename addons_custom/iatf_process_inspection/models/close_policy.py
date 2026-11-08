"""Optional approval for PASS closure; never relax NG or original-input guards."""
import hashlib
import json

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_KEY = 'pqc.close_approval'
_TOKEN = object()
_PROTECTED = {'pqc_closure_basis'}


class PqcClosePolicy(models.Model):
    _inherit = 'iatf.process.inspection'

    pqc_closure_basis = fields.Json('PQC 종료 당시 결재 정책·근거', readonly=True, copy=False)

    def _approval_reset_ignored_fields(self):
        return super()._approval_reset_ignored_fields() | _PROTECTED

    def _approval_should_reset(self, vals):
        if self.env.context.get('_pqc_close_service') is _TOKEN:
            vals = {key: value for key, value in vals.items() if key != 'state'}
        return super()._approval_should_reset(vals)

    def _pqc_close_mode(self):
        self.ensure_one()
        self.check_access('write')
        if not self.company_id or (not self.env.su and self.company_id not in self.env.companies):
            raise AccessError(_('허용된 검사 회사의 종료 정책만 사용할 수 있습니다.'))
        return self.env['ops.policy'].with_company(self.company_id).get(_KEY)

    def _pqc_fingerprint(self):
        self.ensure_one()
        self.check_access('read')
        attachments = self.attachment_ids.sorted('id')
        attachments.check_access('read')
        if attachments:
            attachments.flush_recordset()
            self.env.cr.execute('SELECT id FROM ir_attachment WHERE id IN %s ORDER BY id FOR SHARE',
                                [tuple(attachments.ids)])
            attachments.invalidate_recordset()
        files = []
        for attachment in attachments:
            files.append({'id': attachment.id, 'name': attachment.name,
                          'mimetype': attachment.mimetype, 'url': attachment.url,
                          'content': hashlib.sha256(attachment.raw or b'').hexdigest()})
        body = {'source': self._auto_source_payload(), 'notes': self.notes,
                'part_number': self.part_number, 'documents': sorted(self.document_ids.ids),
                'attachments': files}
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                        separators=(',', ':')).encode()).hexdigest()

    def _approval_snapshot(self):
        snapshot = super()._approval_snapshot()
        # Also capture in required/none mode, so enabling reapproval later does
        # not silently accept an unobserved document revision.
        # Keep the basis on the immutable request: a later revision must not
        # replace the original approval's historical inspection fingerprint.
        snapshot['pqc'] = {'version': 1, 'fingerprint': self._pqc_fingerprint()}
        return snapshot

    def _pqc_approval_basis(self, mode):
        self.ensure_one()
        if self.state != 'decided':
            raise UserError(_('합격 판정을 완료한 뒤 결재·종료하십시오.'))
        self._approval_check_approved(_('PQC 합격 종료'))
        fingerprint = self._pqc_fingerprint()
        if mode == 'reapprove':
            previous = (self.approval_request_id.snapshot or {}).get('pqc', {})
            if (previous.get('version') != 1
                    or previous.get('fingerprint') != fingerprint):
                raise UserError(_('상신 이후 검사·첨부 근거가 변경되었습니다. 새 결재로 재승인하십시오.'))
        return {'policy': mode, 'request_id': self.approval_request_id.id,
                'fingerprint': fingerprint, 'closed_by': self.env.uid,
                'closed_at': fields.Datetime.to_string(fields.Datetime.now())}

    @api.model_create_multi
    def create(self, vals_list):
        if any(key in vals or 'default_' + key in self.env.context
               for vals in vals_list for key in _PROTECTED):
            raise UserError(_('PQC 결재·종료 근거는 전용 절차에서 기록합니다.'))
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            for row in records.filtered(lambda r: r.state == 'closed' and r.result == 'pass' and not r._has_ng()):
                if row._pqc_close_mode() != 'none':
                    raise UserError(_('검사를 생성한 뒤 판정·결재·종료 절차를 진행하십시오.'))
            return records

    def write(self, vals):
        internal = self.env.context.get('_pqc_close_service') is _TOKEN
        if not internal and _PROTECTED & vals.keys():
            raise UserError(_('PQC 결재·종료 근거는 직접 변경할 수 없습니다.'))
        if vals.get('state') != 'closed':
            return super().write(vals)
        with self.env.cr.savepoint():
            self.check_access('write')
            self._lock_auto_evidence_records(self)
            for row in self:
                mode = row._pqc_close_mode()
                applies = row.state != 'closed' and vals.get('result', row.result) == 'pass' and not row._has_ng()
                if not applies or mode == 'none':
                    super(PqcClosePolicy, row).write(dict(vals))
                    continue
                if set(vals) != {'state'}:
                    raise UserError(_('검사 변경을 먼저 저장하고 결재한 뒤 종료하십시오.'))
                basis = row._pqc_approval_basis(mode)
                # A verified state-only close is execution of the approval,
                # not an edit which should manufacture another draft request.
                super(PqcClosePolicy, row.with_context(_pqc_close_service=_TOKEN)).write(dict(vals))
                row.with_context(_pqc_close_service=_TOKEN).write({'pqc_closure_basis': basis})
            return True
