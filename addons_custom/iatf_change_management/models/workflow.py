"""4M workflow uses the existing approval engine; no second approval ledger."""
import hashlib
import json

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import is_html_empty

_WORKFLOW = object()
_HISTORY = {'state', 'requested_by', 'reviewed_by', 'review_date', 'approved_by',
            'approval_date', 'implemented_by', 'actual_date', 'verified_by', 'verification_date'}
_FOLLOWUP = {'verification_method', 'verification_result', 'effective', 'notes'}
_SUBJECT = ('title', 'change_type', 'change_category', 'change_source', 'description',
            'reason', 'affected_product_ids', 'affected_process', 'affected_department_ids',
            'before_state', 'after_state', 'risk_assessment', 'risk_level', 'planned_date',
            'customer_notification_required', 'customer_id', 'customer_approval',
            'customer_approval_date', 'fmea_updated', 'control_plan_updated',
            'work_instruction_updated', 'ppap_required', 'document_ids', 'attachment_ids',
            'company_id', 'requested_by', 'reviewer_id', 'verification_owner_id')


class ChangeWorkflow(models.Model):
    _inherit = 'iatf.change.request'

    reviewer_id = fields.Many2one('res.users', string='지정 검토자', tracking=True)
    verification_owner_id = fields.Many2one('res.users', string='지정 검증자', tracking=True)

    def _change_internal(self):
        return self.env.context.get('_change_workflow') is _WORKFLOW

    def _change_history_fields(self):
        return _HISTORY

    def _change_followup_fields(self):
        return _FOLLOWUP

    def _change_write(self, values):
        return self.with_context(_change_workflow=_WORKFLOW).write(values)

    def _change_check(self, manager=False):
        self.check_access('write')
        group = 'iatf_change_management.group_change_management_' + ('manager' if manager else 'user')
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_('해당 변경관리 역할이 필요합니다.'))
        if any(r.company_id not in self.env.companies for r in self):
            raise AccessError(_('허용된 회사의 변경요청만 처리할 수 있습니다.'))

    def _change_lock(self, states=None, manager=False):
        self._change_check(manager=manager)
        self._approval_lock()
        if states and any(r.state not in states for r in self):
            raise UserError(_('현재 단계에서는 이 작업을 실행할 수 없습니다.'))

    def _change_check_reviewer(self):
        self.ensure_one()
        if self.env.user != self.reviewer_id or self.env.user in (self.requested_by | self.create_uid):
            raise UserError(_('기안자와 다른 지정 검토자만 검토할 수 있습니다.'))

    def _change_content(self):
        self.ensure_one()
        values = {}
        for name in _SUBJECT:
            field, value = self._fields[name], self[name]
            values[name] = sorted(value.ids) if field.relational else str(value) if field.type in ('date', 'datetime') and value else value
        return values

    def _change_digest(self):
        return hashlib.sha256(json.dumps(self._change_content(), sort_keys=True,
            ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

    def _approval_snapshot(self):
        snapshot = super()._approval_snapshot()
        snapshot['change'] = {'version': 1, 'digest': self._change_digest(), 'content': self._change_content()}
        return snapshot

    def _approval_validate_submit(self):
        super()._approval_validate_submit()
        self._change_lock(('review',))
        if any(not r.reviewed_by or r.reviewed_by == r.requested_by for r in self):
            raise UserError(_('독립 검토를 완료한 뒤 결재를 상신하십시오.'))

    def _approval_validate_step(self):
        super()._approval_validate_step()
        self._change_lock(('review',))
        self._change_check_snapshot()

    def _approval_new_revision(self, previous):
        if any(r.state in ('approved', 'implementing', 'verification', 'closed') for r in self):
            raise UserError(_('승인·적용한 변경의 결재는 보존합니다. 적용 전에는 반려 후 보완하십시오.'))
        return super()._approval_new_revision(previous)

    def action_reject_approval(self):
        result = super().action_reject_approval()
        rejected = self.filtered(lambda r: r.state == 'review' and r.approval_state == 'rejected')
        rejected._change_write({'state': 'rejected'})
        return result

    def _change_check_snapshot(self):
        for record in self:
            saved = (record.approval_request_id.snapshot or {}).get('change', {})
            if saved.get('version') != 1 or saved.get('digest') != record._change_digest():
                raise UserError(_('승인 대상 변경 내용이 상신 내용과 다릅니다. 반려 후 재검토하십시오.'))

    def _approval_should_reset(self, vals):
        if self._change_internal() and set(vals) <= self._change_history_fields():
            return False
        if set(vals) <= self._change_followup_fields() and all(r.state == 'verification' for r in self):
            return False
        return super()._approval_should_reset(vals)

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(v) for v in vals_list]
        for values in vals_list:
            if values.get('state', self.env.context.get('default_state', 'draft')) != 'draft':
                raise UserError(_('변경요청은 초안에서 시작하십시오.'))
            for name in _HISTORY - {'state', 'requested_by'}:
                if values.get(name, self.env.context.get('default_' + name)):
                    raise UserError(_('변경 처리 이력은 단계별 액션으로만 생성합니다.'))
            if values.get('requested_by', self.env.context.get('default_requested_by', self.env.uid)) != self.env.uid:
                raise UserError(_('다른 사람을 기안자로 지정할 수 없습니다.'))
            values['requested_by'] = self.env.uid
        return super().create(vals_list)

    def write(self, vals):
        self._change_lock()
        if not self._change_internal():
            if _HISTORY & vals.keys():
                raise UserError(_('변경 상태와 검토·승인·실행 이력은 단계별 버튼으로만 기록합니다.'))
            operational = self._approval_reset_ignored_fields() | {'approval_line_ids'}
            for record in self:
                allowed = operational | (self._change_followup_fields() if record.state == 'verification' else set())
                if record.state not in ('draft', 'rejected') and set(vals) - allowed:
                    raise UserError(_('제출한 변경 내용은 잠깁니다. 반려·초안 복귀 후 수정하십시오.'))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' for r in self):
            raise UserError(_('처리 이력이 있는 변경요청은 삭제할 수 없습니다.'))
        return super().unlink()

    @api.constrains('company_id', 'reviewer_id', 'verification_owner_id')
    def _check_change_assignees(self):
        for record in self:
            for user in record.reviewer_id | record.verification_owner_id:
                if not user.active or user.share or record.company_id not in user.company_ids:
                    raise ValidationError(_('검토·검증자는 해당 회사의 활성 내부 사용자여야 합니다.'))

    def action_request(self):
        self._change_lock(('draft',))
        for record in self:
            if not record.reviewer_id or not record.verification_owner_id or record.reviewer_id == record.requested_by:
                raise UserError(_('기안자와 다른 검토자와 담당 검증자를 지정하십시오.'))
            record.with_user(record.reviewer_id).check_access('write')
            if is_html_empty(record.description) or is_html_empty(record.reason):
                raise UserError(_('변경 내용과 사유를 입력하십시오.'))
        return self._change_write({'state': 'requested'})

    def action_review(self):
        self._change_lock(('requested',))
        for record in self:
            record._change_check_reviewer()
        return self._change_write({'state': 'review', 'reviewed_by': self.env.uid,
                                   'review_date': fields.Date.context_today(self)})

    def action_approve(self):
        self._change_lock(('review',), manager=True)
        for record in self:
            if self.env.user in (record.requested_by | record.create_uid):
                raise UserError(_('기안자는 자신의 변경요청을 승인할 수 없습니다.'))
            record._approval_check_approved(_('변경 승인 확정'))
            record._change_check_snapshot()
            if record.customer_notification_required and record.customer_approval != 'approved':
                raise UserError(_('고객 승인 필요 건은 승인 근거를 먼저 확보하십시오.'))
            record._change_write({'state': 'approved',
                'approved_by': record.approval_request_id.line_ids.sorted(lambda l: (l.sequence, l.id))[-1].user_id.id,
                'approval_date': fields.Date.context_today(record)})
        return True

    def action_implement(self):
        self._change_lock(('approved',), manager=True)
        self._approval_check_approved(_('변경 실행'))
        self._change_check_snapshot()
        return self._change_write({'state': 'implementing', 'implemented_by': self.env.uid,
                                   'actual_date': fields.Date.context_today(self)})

    def action_verify(self):
        self._change_lock(('implementing',))
        return self._change_write({'state': 'verification'})

    def action_close(self):
        self._change_lock(('verification',))
        for record in self:
            if self.env.user != record.verification_owner_id or self.env.user == record.implemented_by:
                raise UserError(_('실행자와 다른 지정 검증자가 검증을 종료해야 합니다.'))
            if is_html_empty(record.verification_result) or record.effective != 'yes':
                raise UserError(_('검증 결과와 유효성 확인을 입력하십시오.'))
        return self._change_write({'state': 'closed', 'verified_by': self.env.uid,
                                   'verification_date': fields.Date.context_today(self)})

    def action_reject(self):
        self._change_lock(('requested', 'review', 'approved'), manager=True)
        if any(self.env.user in (r.requested_by | r.create_uid) for r in self):
            raise UserError(_('기안자는 자신의 변경요청을 반려 처리할 수 없습니다.'))
        return self._change_write({'state': 'rejected'})

    def action_change_reset_draft(self):
        self._change_lock(('rejected',))
        for record in self:
            if record.approval_request_id and record.approval_request_id.state != 'draft':
                record._approval_new_revision(record.approval_request_id)
        return self._change_write({'state': 'draft', 'reviewed_by': False, 'review_date': False,
                                   'approved_by': False, 'approval_date': False})


class ApprovalManagement(models.Model):
    _inherit = 'iatf.approval.request'

    @api.model
    def _approval_management_roles(self):
        roles = super()._approval_management_roles()
        return dict(roles, **{'iatf.change.request': 'iatf_change_management.group_change_management_manager'})
