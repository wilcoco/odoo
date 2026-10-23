"""Bind SQ approval to immutable content; lifecycle transitions keep approval."""
import hashlib
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .assessment import LOCKED

_TRANSITION = object()
_CONTENT = {
    'title', 'audit_type', 'planned_date', 'actual_date', 'department_id',
    'process_name', 'standard_reference', 'lead_auditor_id', 'auditor_ids',
    'vda_score', 'vda_grade', 'audit_report', 'document_ids', 'attachment_ids',
    'company_id', 'sq_standard_id', 'sq_date_from', 'sq_date_to', 'sq_ratios',
    'sq_line_ids', 'finding_ids', 'sq_revision_of_id',
}
_FINDING_CONTENT = {'audit_id', 'finding_type', 'clause_reference', 'description',
                    'objective_evidence', 'responsible_id', 'due_date', 'attachment_ids'}


class SqAudit(models.Model):
    _inherit = 'iatf.audit'

    sq_revision_of_id = fields.Many2one(
        'iatf.audit', string='이전 SQ 평가서', readonly=True, copy=False, ondelete='restrict')

    @api.constrains('sq_revision_of_id', 'company_id', 'audit_type')
    def _sq_revision_company(self):
        for audit in self.filtered('sq_revision_of_id'):
            previous = audit.sq_revision_of_id
            previous.check_access('read')
            if audit.audit_type != 'sq' or previous.audit_type != 'sq' or previous.company_id != audit.company_id or previous == audit:
                raise ValidationError(_('같은 회사의 다른 SQ 평가서만 이전 평가로 연결할 수 있습니다.'))

    def _sq_content(self):
        self.ensure_one()
        data = {}
        for name in sorted(_CONTENT - {'sq_line_ids', 'finding_ids'}):
            value = self[name]
            field = self._fields[name]
            if field.type in ('many2one', 'one2many', 'many2many'):
                value = sorted(value.ids)
            elif field.type in ('date', 'datetime'):
                value = str(value) if value else False
            data[name] = value
        data['lines'] = [{
            'id': line.id, 'item': line.item_id.id, 'code': line.item_id.code,
            'points': line.points, 'requirement': line.requirement_snapshot,
            'rating': line.rating, 'reason': line.reason, 'finding': line.finding,
            'action': line.action, 'evidence': line.evidence_snapshot,
        } for line in self.sq_line_ids.sorted('id')]
        data['findings'] = [{
            'id': line.id, 'type': line.finding_type, 'clause': line.clause_reference,
            'description': line.description, 'evidence': line.objective_evidence,
            'responsible': line.responsible_id.id, 'due': str(line.due_date) if line.due_date else False,
            'attachments': sorted(line.attachment_ids.ids),
        } for line in self.finding_ids.sorted('id')]
        return data

    def _sq_content_digest(self):
        payload = json.dumps(self._sq_content(), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(payload.encode()).hexdigest()

    def _approval_snapshot(self):
        snapshot = super()._approval_snapshot()
        if self.audit_type == 'sq':
            # Source versions describe the submission time; later source edits
            # never rewrite this historical snapshot or the original judgment.
            snapshot['sq'] = {
                'version': 1, 'digest': self._sq_content_digest(), 'content': self._sq_content(),
                'documents': [{'id': doc.id, 'write_date': str(doc.write_date)} for doc in self.document_ids],
                'attachments': [{'id': a.id, 'checksum': a.checksum} for a in self.attachment_ids],
            }
        return snapshot

    def _approval_validate_submit(self):
        super()._approval_validate_submit()
        for audit in self.filtered(lambda r: r.audit_type == 'sq'):
            if audit.state not in ('planned', 'in_progress'):
                raise UserError(_('발행된 SQ 평가는 재평가서를 작성하여 상신하십시오.'))
            audit._sq_validate_complete()

    def _approval_validate_step(self):
        super()._approval_validate_step()
        self.filtered(lambda r: r.audit_type == 'sq')._sq_check_snapshot()

    def _sq_check_snapshot(self):
        for audit in self:
            saved = (audit.approval_request_id.snapshot or {}).get('sq', {})
            if saved.get('version') != 1 or saved.get('digest') != audit._sq_content_digest():
                raise UserError(_('상신한 SQ 평가 내용과 현재 내용이 다릅니다. 새 결재로 다시 상신하십시오.'))
            if audit.state in ('planned', 'in_progress'):
                attachments = {row['id']: row['checksum'] for row in saved.get('attachments', [])}
                documents = {row['id']: row['write_date'] for row in saved.get('documents', [])}
                if any(attachments.get(a.id) != a.checksum for a in audit.attachment_ids) or any(
                        documents.get(d.id) != str(d.write_date) for d in audit.document_ids):
                    raise UserError(_('상신 이후 연결 문서 또는 첨부가 변경됐습니다. 근거를 재확인하고 다시 상신하십시오.'))

    def _approval_should_reset(self, vals):
        if self.env.context.get('_sq_transition') is _TRANSITION and set(vals) == {'state'}:
            return False
        return super()._approval_should_reset(vals)

    def _sq_child_changed(self):
        for audit in self.filtered(lambda r: r.audit_type == 'sq'):
            request = audit.approval_request_id
            if request and request.state in ('in_progress', 'approved'):
                audit._approval_new_revision(request)

    def write(self, vals):
        sq = self.filtered(lambda r: r.audit_type == 'sq')
        if sq:
            sq._approval_lock()
            if 'state' in vals and self.env.context.get('_sq_transition') is not _TRANSITION:
                raise UserError(_('SQ 평가 상태는 시작·발행·후속·종료·취소 버튼으로 변경하십시오.'))
            if any(r.state in LOCKED for r in sq) and (_CONTENT | {'approval_request_id'}) & vals.keys():
                raise UserError(_('발행된 평가와 결재는 보존합니다. 재평가서 작성 버튼을 사용하십시오.'))
        return super().write(vals)

    def action_start(self):
        sq = self.filtered(lambda r: r.audit_type == 'sq')
        other = self - sq
        if other:
            super(SqAudit, other).action_start()
        for audit in sq:
            audit._approval_lock()
            if audit.state != 'planned':
                raise UserError(_('계획 상태의 SQ 평가만 시작할 수 있습니다.'))
            super(SqAudit, audit.with_context(_sq_transition=_TRANSITION)).action_start()
        return True

    def _sq_transition_to(self, target, allowed, approved=True):
        for audit in self:
            audit._approval_lock()
            if audit.state not in allowed:
                raise UserError(_('현재 단계에서는 이 상태 전환을 실행할 수 없습니다.'))
            if approved:
                audit._sq_validate_complete()
                audit._approval_check_approved(_('SQ 평가 발행·종료'))
                audit._sq_check_snapshot()
            if target == 'closed' and audit.finding_ids.filtered(lambda f: f.state != 'closed'):
                raise UserError(_('미종료 지적사항을 처리한 뒤 평가를 종료하십시오.'))
            audit.with_context(_sq_transition=_TRANSITION).write({'state': target})
        return True

    def action_issue_report(self):
        sq = self.filtered(lambda r: r.audit_type == 'sq')
        other = self - sq
        if other:
            super(SqAudit, other).action_issue_report()
        return sq._sq_transition_to('report', ('planned', 'in_progress'))

    def action_follow_up(self):
        sq = self.filtered(lambda r: r.audit_type == 'sq')
        if self - sq:
            super(SqAudit, self - sq).action_follow_up()
        return sq._sq_transition_to('follow_up', ('report',))

    def action_close(self):
        sq = self.filtered(lambda r: r.audit_type == 'sq')
        if self - sq:
            super(SqAudit, self - sq).action_close()
        return sq._sq_transition_to('closed', ('report', 'follow_up'))

    def action_cancel(self):
        sq = self.filtered(lambda r: r.audit_type == 'sq')
        if self - sq:
            super(SqAudit, self - sq).action_cancel()
        return sq._sq_transition_to('cancelled', ('planned', 'in_progress', 'report', 'follow_up'), approved=False)

    def action_sq_revise(self):
        self.ensure_one()
        self._approval_lock()
        if self.audit_type != 'sq' or self.state not in LOCKED:
            raise UserError(_('발행·종료·취소한 SQ 평가에서 재평가서를 작성하십시오.'))
        values = {name: self[name] for name in ('title', 'audit_type', 'process_name', 'standard_reference')}
        values.update(title=_('%s (재평가)') % self.title, company_id=self.company_id.id,
                      planned_date=fields.Date.context_today(self), lead_auditor_id=self.env.uid,
                      sq_standard_id=self.sq_standard_id.id, sq_revision_of_id=self.id,
                      sq_date_from=self.sq_date_from, sq_date_to=self.sq_date_to)
        revised = self.create(values)
        revised.action_sq_initialize()
        old = {line.item_id.id: line for line in self.sq_line_ids}
        for line in revised.sq_line_ids:
            previous = old.get(line.item_id.id)
            if previous:
                line.write({name: previous[name] for name in ('rating', 'reason', 'finding', 'action')})
        revised.message_post(body=_('이전 평가 %s를 보존하여 재평가서를 작성했습니다. 증빙은 다시 조회하십시오.') % self.name)
        return {'type': 'ir.actions.act_window', 'res_model': 'iatf.audit', 'res_id': revised.id,
                'view_mode': 'form', 'target': 'current'}


class SqLine(models.Model):
    _inherit = 'sq.assessment.line'

    def write(self, vals):
        audits = self.audit_id
        audits._approval_lock()
        result = super().write(vals)
        if {'rating', 'reason', 'finding', 'action', 'evidence_snapshot'} & vals.keys():
            audits._sq_child_changed()
        return result

    def unlink(self):
        audits = self.audit_id
        audits._approval_lock()
        result = super().unlink()
        audits._sq_child_changed()
        return result


class SqFinding(models.Model):
    _inherit = 'iatf.audit.finding'

    @api.model_create_multi
    def create(self, vals_list):
        ids = [v.get('audit_id', self.env.context.get('default_audit_id')) for v in vals_list]
        audits = self.env['iatf.audit'].browse([i for i in ids if i]).filtered(lambda r: r.audit_type == 'sq')
        audits._approval_lock()
        if any(a.state in LOCKED for a in audits):
            raise UserError(_('발행된 SQ 평가의 지적 내용은 재평가서에서 추가하십시오.'))
        result = super().create(vals_list)
        audits._sq_child_changed()
        return result

    def write(self, vals):
        audits = self.audit_id.filtered(lambda r: r.audit_type == 'sq')
        if vals.get('audit_id'):
            audits |= self.env['iatf.audit'].browse(vals['audit_id']).filtered(lambda r: r.audit_type == 'sq')
        audits._approval_lock()
        if _FINDING_CONTENT & vals.keys() and any(a.state in LOCKED for a in audits):
            raise UserError(_('발행된 SQ 평가의 지적 내용은 변경할 수 없습니다. 후속 조치만 기록하십시오.'))
        if vals and any(a.state in ('closed', 'cancelled') for a in audits):
            raise UserError(_('종료·취소된 SQ 평가의 후속 조치는 변경할 수 없습니다.'))
        result = super().write(vals)
        if _FINDING_CONTENT & vals.keys():
            audits._sq_child_changed()
        return result

    def unlink(self):
        audits = self.audit_id.filtered(lambda r: r.audit_type == 'sq')
        audits._approval_lock()
        if any(a.state in LOCKED for a in audits):
            raise UserError(_('발행된 SQ 평가의 지적사항은 삭제할 수 없습니다.'))
        result = super().unlink()
        audits._sq_child_changed()
        return result
