from odoo import api, models, _
from odoo.exceptions import UserError

_LEAVE_TRANSITION = object()


def _transition(records):
    return records.with_context(_ops_leave_transition=_LEAVE_TRANSITION)


class OpsLeave(models.Model):
    _inherit = 'hr.leave'

    def _ops_two_step(self):
        return self.filtered(lambda leave: leave.validation_type == 'both' and not
            self.env['cams.ops.policy']._value(leave.company_id, 'leave_hr_skip_manager'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and self.env.context.get('_ops_leave_transition') is not _LEAVE_TRANSITION:
            for vals in vals_list:
                state = vals.get('state', self.env.context.get('default_state', 'confirm'))
                if state in ('validate1', 'validate') or any(vals.get(k) or self.env.context.get('default_' + k)
                        for k in ('first_approver_id', 'second_approver_id')):
                    raise UserError(_('휴가 승인 상태는 승인 절차에서만 기록합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if (not self.env.su and self._ops_two_step()
                and self.env.context.get('_ops_leave_transition') is not _LEAVE_TRANSITION):
            if vals.get('state') in ('validate1', 'validate') or set(vals) & {'first_approver_id', 'second_approver_id'}:
                raise UserError(_('2단계 휴가는 지정 관리자와 인사 담당자의 승인 버튼을 사용하십시오.'))
            if any(l.state in ('validate1', 'validate') for l in self) and set(vals) & {
                    'employee_id', 'holiday_status_id', 'request_date_from', 'request_date_to',
                    'date_from', 'date_to', 'request_hour_from', 'request_hour_to',
                    'request_unit_half', 'request_unit_hours', 'number_of_days'}:
                raise UserError(_('승인된 휴가 내용은 취소 후 다시 신청하십시오.'))
        return super().write(vals)

    def action_approve(self, check_state=True):
        for leave in self._ops_two_step():
            if (leave.state != 'confirm' or leave.employee_id.leave_manager_id != self.env.user
                    or leave.employee_id.user_id == self.env.user or not self.env.user.employee_id):
                raise UserError(_('2단계 휴가의 1차 승인은 신청자의 지정 휴가 관리자가 수행해야 합니다.'))
        return super(OpsLeave, _transition(self)).action_approve(check_state=check_state)

    def action_validate(self, check_state=True):
        for leave in self._ops_two_step():
            if (leave.state != 'validate1' or not leave.first_approver_id
                    or leave.first_approver_id.user_id == self.env.user
                    or leave.employee_id.user_id == self.env.user
                    or not self.env.user.employee_id):
                raise UserError(_('2단계 휴가는 관리자 1차 승인을 완료한 뒤 최종 승인하십시오.'))
        return super(OpsLeave, _transition(self)).action_validate(check_state=check_state)

    def action_reset_confirm(self):
        return super(OpsLeave, _transition(self)).action_reset_confirm()

    def action_refuse(self):
        return super(OpsLeave, _transition(self)).action_refuse()

    def _split_leaves(self, split_date_from, split_date_to):
        # Odoo's private public-holiday adjustment preserves a previously approved leave.
        return super(OpsLeave, _transition(self))._split_leaves(split_date_from, split_date_to)
