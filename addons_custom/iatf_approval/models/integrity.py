"""Approval snapshots and scoped management on the current approval guard."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.osv import expression
from .approval_guard import _internal, _is_internal


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    next_request_ids = fields.One2many('iatf.approval.request', 'previous_request_id', readonly=True, copy=False)
    snapshot = fields.Json(readonly=True, copy=False)
    can_manage = fields.Boolean(compute='_compute_can_manage', search='_search_can_manage')

    @api.model
    def _approval_management_roles(self):
        """Business modules opt in their existing document-management roles."""
        return {}

    @api.model
    def _management_domain(self):
        # Odoo expands record-rule domains with sudo while retaining the uid.
        # Restore that user's ACLs/rules before querying the source document.
        self = self.sudo(False)
        domains = []
        for model_name, group_xmlid in self._approval_management_roles().items():
            if not self.env.user.has_group(group_xmlid):
                continue
            target = self.env[model_name].with_context(active_test=False)
            if not target.has_access('read') or not target.has_access('write'):
                continue
            # Resolve at query time, not inside the cached ir.rule evaluation.
            # The subquery applies read rules; add write rules and company scope.
            domain = [('company_id', 'in', self.env.companies.ids)]
            domain = expression.AND([domain, self.env['ir.rule']._compute_domain(model_name, 'write')])
            domains.append([('res_model', '=', model_name), ('res_id', 'in', target._search(domain))])
        return expression.OR(domains)

    @api.model
    def _search_can_manage(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise ValueError('can_manage supports boolean equality only')
        domain = self._management_domain()
        return domain if (value == (operator == '=')) else ['!'] + domain

    @api.depends_context('uid', 'allowed_company_ids')
    def _compute_can_manage(self):
        # No request search here: its record rule itself uses can_manage.
        roles = self._approval_management_roles()
        for request in self:
            group = roles.get(request.res_model)
            target = request._get_target_record() if group else False
            request.can_manage = bool(
                group and self.env.user.has_group(group) and target.exists()
                and target.has_access('read') and target.has_access('write')
                and target.company_id in self.env.companies)

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([dict(vals, snapshot=False) for vals in vals_list])

    def write(self, vals):
        if 'snapshot' in vals and not _is_internal(self.env):
            raise UserError(_('승인 스냅샷은 상신 절차에서만 기록합니다.'))
        return super().write(vals)

    def action_submit(self):
        with self.env.cr.savepoint():
            for request in self:
                target = request._lock_workflow()
                if request.state == 'draft' and request.guard_version:
                    target._approval_validate_submit()
                    _internal(request).write({'snapshot': target._approval_snapshot()})
            return super().action_submit()

    def action_reject(self, reason=None):
        for request in self:
            target = request._check_target()
            super(ApprovalRequest, request).action_reject(
                reason=target._approval_rejection_reason(reason))
        return True


class ApprovalMixin(models.AbstractModel):
    _inherit = 'iatf.approval.mixin'

    def _approval_lock(self):
        self._approval_lock_target()
        self.invalidate_recordset()

    def _approval_validate_submit(self):
        self.check_access('write')

    def _approval_rejection_reason(self, reason):
        return reason

    def _approval_snapshot(self):
        self.ensure_one()
        return {'model': self._name, 'id': self.id, 'name': self.display_name}
