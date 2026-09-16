"""Server-owned decisions and immutable previous approval revisions."""
from psycopg2 import sql

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


_TRANSITION = object()


def internal(records):
    return records.with_context(_approval_transition=_TRANSITION)


def trusted(env):
    return env.context.get('_approval_transition') is _TRANSITION


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    previous_request_id = fields.Many2one('iatf.approval.request', readonly=True, copy=False, ondelete='restrict')
    snapshot = fields.Json(readonly=True, copy=False)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        for field in ('current_line_id', 'current_approver_id', 'snapshot', 'previous_request_id', 'approved_date', 'rejected_date'):
            vals.pop(field, None)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self.env):
            raise AccessError(_('결재 요청은 원문서에서 생성해 주세요.'))
        return super().create([dict(v, state='draft', approved_date=False, rejected_date=False,
                                    snapshot=False, previous_request_id=v.get('previous_request_id', False)) for v in vals_list])

    def _check_current(self, operation='write'):
        for request in self:
            target = request._get_target_record().exists()
            if not target or target.approval_request_id != request:
                raise UserError(_('현재 원문서의 결재 버전이 아닙니다.'))
            target.check_access(operation)
        return True

    def _lock_current(self, operation='write'):
        self._check_current(operation)
        for request in self.sorted('id'):
            target = request._get_target_record()
            target._approval_lock()
        self.invalidate_recordset()
        self.line_ids.invalidate_recordset()
        self._check_current(operation)

    def write(self, vals):
        if not trusted(self.env):
            if set(vals) - {'line_ids'}:
                raise AccessError(_('결재 상태·일시·원문서 연결은 직접 변경할 수 없습니다.'))
            self._lock_current()
            if any(r.state != 'draft' for r in self):
                raise UserError(_('진행 중이거나 종료된 결재선은 변경할 수 없습니다. 새 결재 버전을 만드세요.'))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' or r.previous_request_id for r in self):
            raise UserError(_('결재 이력은 삭제할 수 없습니다.'))
        if not trusted(self.env):
            raise AccessError(_('결재 요청은 원문서에서 관리해 주세요.'))
        return super().unlink()

    def action_submit(self):
        self._lock_current()
        for request in self:
            if request.state != 'draft':
                raise UserError(_('초안 결재만 상신할 수 있습니다.'))
            target = request._get_target_record()
            target._approval_validate_submit()
            internal(request).write({'snapshot': target._approval_snapshot()})
        return super(ApprovalRequest, internal(self)).action_submit()

    def action_approve(self):
        self._lock_current('read')
        return super(ApprovalRequest, internal(self)).action_approve()

    def action_reject(self, reason=None):
        self._lock_current('read')
        for request in self:
            reason = request._get_target_record()._approval_rejection_reason(reason)
            super(ApprovalRequest, internal(request)).action_reject(reason=reason)
        return True

    def action_reset_draft(self):
        self._lock_current()
        for request in self:
            if request.state == 'draft':
                continue
            target = request._get_target_record()
            request._clear_activities(target)
            new = internal(self.env['iatf.approval.request']).create({
                'res_model': request.res_model, 'res_id': request.res_id,
                'requester_id': self.env.uid, 'previous_request_id': request.id,
                'line_ids': [(0, 0, {'sequence': line.sequence, 'user_id': line.user_id.id})
                             for line in request._get_ordered_lines()],
            })
            internal(target).write({'approval_request_id': new.id})
        return True


class ApprovalLine(models.Model):
    _inherit = 'iatf.approval.line'

    def _check_editable_requests(self, requests):
        requests._lock_current()
        if any(r.state != 'draft' for r in requests):
            raise UserError(_('진행 중이거나 종료된 결재선은 변경할 수 없습니다.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self.env):
            if any(set(v) & {'state', 'action_date', 'note', 'is_current'} for v in vals_list):
                raise AccessError(_('결재 판정은 승인/반려 동작으로만 기록됩니다.'))
            self._check_editable_requests(self.env['iatf.approval.request'].browse([v.get('request_id') for v in vals_list if v.get('request_id')]))
        return super().create([dict(v, state='new', action_date=False, note=False) for v in vals_list])

    def write(self, vals):
        if not trusted(self.env):
            if set(vals) - {'sequence', 'user_id', 'request_id'}:
                raise AccessError(_('결재 판정은 직접 변경할 수 없습니다.'))
            requests = self.request_id | self.env['iatf.approval.request'].browse(vals.get('request_id', []))
            self._check_editable_requests(requests)
        return super().write(vals)

    def unlink(self):
        self._check_editable_requests(self.request_id)
        return super().unlink()


class ApprovalMixin(models.AbstractModel):
    _inherit = 'iatf.approval.mixin'

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        for field in ('approval_request_id', 'approval_state', 'approval_current_approver_id'):
            vals.pop(field, None)
        return vals

    def _approval_lock(self):
        """A write fence makes concurrent repeatable-read snapshots retry."""
        if self:
            self.flush_recordset()
            self.env.cr.execute(sql.SQL('SELECT id FROM {} WHERE id IN %s ORDER BY id FOR UPDATE').format(sql.Identifier(self._table)), [tuple(sorted(self.ids))])
            self.env.cr.execute(sql.SQL('UPDATE {} SET write_date=write_date WHERE id IN %s').format(sql.Identifier(self._table)), [tuple(sorted(self.ids))])
            self.invalidate_recordset()

    def _approval_validate_submit(self):
        self.check_access('write')

    def _approval_rejection_reason(self, reason):
        return reason

    def _approval_snapshot(self):
        self.ensure_one()
        return {'model': self._name, 'id': self.id, 'name': self.display_name}

    def _approval_ensure_request(self):
        return super(ApprovalMixin, internal(self))._approval_ensure_request()

    @api.model_create_multi
    def create(self, vals_list):
        if not trusted(self.env) and any(set(v) & {'approval_request_id', 'approval_state', 'approval_current_approver_id'} for v in vals_list):
            raise AccessError(_('결재 연결과 상태는 직접 지정할 수 없습니다.'))
        return super().create([dict(v) for v in vals_list])

    def write(self, vals):
        vals = dict(vals)
        if not trusted(self.env) and set(vals) & {'approval_request_id', 'approval_state', 'approval_current_approver_id'}:
            raise AccessError(_('결재 연결과 상태는 직접 변경할 수 없습니다.'))
        if self._approval_should_reset(vals):
            self.check_access('write')
            self._approval_lock()
            # The existing mixin resets approved documents after write. Also
            # invalidate in-progress decisions without erasing the old lines.
            for record in self.filtered(lambda r: r.approval_state == 'in_progress'):
                record.action_reset_approval()
        return super().write(vals)

    def unlink(self):
        if any(r.approval_request_id.state != 'draft' or r.approval_request_id.previous_request_id for r in self if r.approval_request_id):
            raise UserError(_('결재 이력이 있는 문서는 삭제할 수 없습니다.'))
        return super(ApprovalMixin, internal(self)).unlink()

    def _approval_check_approved(self, action_label=None):
        for record in self:
            request = record.approval_request_id
            if not request or request.res_model != record._name or request.res_id != record.id:
                raise UserError(_('원문서의 유효한 결재 연결이 필요합니다.'))
            if not request.line_ids or any(line.state != 'approved' for line in request.line_ids):
                raise UserError(_('모든 결재 단계의 승인이 필요합니다.'))
        return super()._approval_check_approved(action_label)
