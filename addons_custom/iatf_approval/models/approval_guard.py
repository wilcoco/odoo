"""Server capabilities and evidence preservation for the shared approval engine."""
from collections import defaultdict
from copy import deepcopy
from lxml import etree

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, MissingError, UserError
from odoo.osv import expression
from odoo.tools import SQL

_APPROVAL_TOKEN = object()
_APPROVAL_CONTEXT = '_iatf_approval_service'
_REQUEST_PROTECTED = {'res_model', 'res_id', 'requester_id', 'company_id', 'guard_version',
                      'previous_request_id', 'state', 'approved_date', 'rejected_date',
                      'current_line_id', 'current_approver_id'}
_MIXIN_PROTECTED = {'approval_request_id', 'approval_state', 'approval_current_approver_id',
                    'approval_is_current_user', 'approval_current_line_id'}


def _internal(record):
    return record.with_context(**{_APPROVAL_CONTEXT: _APPROVAL_TOKEN})


def _is_internal(env):
    return env.context.get(_APPROVAL_CONTEXT) is _APPROVAL_TOKEN


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    company_id = fields.Many2one('res.company', readonly=True, index=True)
    guard_version = fields.Integer(readonly=True, default=0,
        help='0: 기존 자료 — 새 검증 절차의 승인 증거로 자동 인정하지 않습니다.')
    previous_request_id = fields.Many2one('iatf.approval.request', readonly=True, ondelete='restrict')

    def _get_target_record(self):
        self.ensure_one()
        if self.res_model not in self.env or self.res_id <= 0:
            raise UserError(_('유효한 결재 대상 문서가 없습니다.'))
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record or 'approval_request_id' not in record._fields:
            raise UserError(_('결재를 지원하는 실제 대상 문서가 필요합니다.'))
        return record

    def _check_target(self, operation='write', current=True):
        self.ensure_one()
        record = self._get_target_record()
        record.check_access(operation)
        company = record.company_id if 'company_id' in record._fields else self.company_id
        if not self.env.su and self.company_id not in self.env.companies:
            raise AccessError(_('허용된 회사의 결재만 처리할 수 있습니다.'))
        if company != self.company_id:
            raise UserError(_('결재 요청과 대상 문서의 회사가 다릅니다. 새 결재가 필요합니다.'))
        if current and record.approval_request_id != self:
            raise UserError(_('현재 문서의 결재 요청이 아닙니다. 과거 결재는 변경할 수 없습니다.'))
        return record

    def _check_access(self, operation):
        result = super()._check_access(operation)
        if result or self.env.su:
            return result
        for request in self.sudo():
            try:
                record = self.env[request.res_model].browse(request.res_id)
                record.check_access('read' if operation == 'read' else 'write')
                if not record.exists():
                    raise AccessError(_('대상 문서를 찾을 수 없습니다.'))
            except (AccessError, MissingError, KeyError):
                return self.browse(request.id), lambda: AccessError(_('대상 문서 접근 권한이 없습니다.'))
        return None

    def _search(self, domain, offset=0, limit=None, order=None):
        if not self.env.su:
            # A polymorphic res_model/res_id has no SQL foreign key for target
            # record rules. Filter through each actual target model's ORM rules.
            candidates = self.sudo().search(expression.AND([
                domain, [('company_id', 'in', self.env.companies.ids)]]))
            grouped = defaultdict(list)
            for request in candidates:
                grouped[request.res_model].append(request.res_id)
            allowed = []
            for model, ids in grouped.items():
                if model not in self.env:
                    continue
                try:
                    targets = self.env[model].search([('id', 'in', ids)])
                except AccessError:
                    continue
                allowed.append([('res_model', '=', model), ('res_id', 'in', targets.ids)])
            domain = expression.AND([domain, expression.OR(allowed) if allowed else [('id', '=', 0)]])
        return super()._search(domain, offset=offset, limit=limit, order=order)

    @api.model_create_multi
    def create(self, vals_list):
        if not _is_internal(self.env):
            raise UserError(_('결재 요청은 대상 문서의 결재 기능에서 생성하세요.'))
        safe_vals = []
        for vals in vals_list:
            vals = dict(vals)
            record = self.env[vals['res_model']].browse(vals['res_id']).exists()
            if not record or 'approval_request_id' not in record._fields:
                raise UserError(_('유효한 결재 대상 문서가 필요합니다.'))
            record.check_access('write')
            company = record.company_id if 'company_id' in record._fields else self.env.company
            if not company or (not self.env.su and company not in self.env.companies):
                raise AccessError(_('허용된 회사의 문서에만 결재를 생성할 수 있습니다.'))
            vals.update(company_id=company.id, guard_version=1, state='draft',
                        approved_date=False, rejected_date=False, requester_id=self.env.uid,
                        previous_request_id=vals.get('previous_request_id', False),
                        line_ids=vals.get('line_ids', []))
            safe_vals.append(vals)
        return super().create(safe_vals)

    def write(self, vals):
        if not _is_internal(self.env):
            if _REQUEST_PROTECTED & vals.keys():
                raise UserError(_('결재 결과·대상·승인 근거는 공개 결재 액션으로만 기록합니다.'))
            for request in self:
                request._check_target()
                if vals and request.state != 'draft':
                    raise UserError(_('상신한 결재 근거는 수정할 수 없습니다. 새 결재를 만드세요.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('결재 요청과 과거 승인 근거는 삭제할 수 없습니다.'))

    def _lock_workflow(self):
        self.ensure_one()
        record = self._check_target()
        record._approval_lock_target()
        self.flush_recordset()
        self.env.cr.execute('UPDATE iatf_approval_request SET write_date = write_date WHERE id = %s', [self.id])
        self.invalidate_recordset()
        self.env['iatf.approval.line'].invalidate_model()
        self._check_target()
        return record

    def _validate_approvers(self):
        self.ensure_one()
        for line in self.line_ids:
            user = line.user_id
            if not user.active or user.share or self.company_id not in user.company_ids:
                raise UserError(_('해당 회사의 활성 내부 사용자를 결재자로 지정하세요.'))
            self._get_target_record().with_user(user).check_access('write')

    def action_submit(self):
        with self.env.cr.savepoint():
            for request in self:
                record = request._lock_workflow()
                if request.state == 'rejected' or not request.guard_version:
                    record._approval_new_revision(request)
                    record.approval_request_id.action_submit()
                    continue
                if request.state != 'draft':
                    raise UserError(_('초안 결재만 상신할 수 있습니다.'))
                request._validate_approvers()
                super(ApprovalRequest, _internal(request)).action_submit()
        return True

    def action_approve(self, expected_line_id=None):
        if expected_line_id is not None:
            self.ensure_one()
            self = self.with_context(approval_expected_line_id=expected_line_id)
        return super().action_approve()

    def _approve_user(self, user):
        with self.env.cr.savepoint():
            self._lock_workflow()
            expected = self.env.context.get('approval_expected_line_id')
            if expected is not None and (type(expected) is not int or
                                         expected != self.current_line_id.id):
                raise UserError(_('화면의 결재 단계가 현재 단계와 다릅니다. 갱신 후 다시 확인하세요.'))
            if expected is None and len(self.line_ids.filtered(lambda line: line.user_id == user)) > 1:
                raise UserError(_('동일 결재자의 반복 단계에는 화면에 표시된 결재 단계 ID가 필요합니다.'))
            if user != self.env.user or not self.guard_version:
                raise UserError(_('현재 사용자의 검증된 결재 절차만 승인할 수 있습니다.'))
            self._validate_approvers()
            return super(ApprovalRequest, _internal(self))._approve_user(user)

    def _reject_user(self, user, reason=None):
        with self.env.cr.savepoint():
            self._lock_workflow()
            if user != self.env.user or not self.guard_version:
                raise UserError(_('현재 사용자의 검증된 결재 절차만 반려할 수 있습니다.'))
            return super(ApprovalRequest, _internal(self))._reject_user(user, reason=reason)

    def action_reset_draft(self):
        with self.env.cr.savepoint():
            for request in self:
                record = request._lock_workflow()
                if request.state != 'draft' or not request.guard_version:
                    record._approval_new_revision(request)
        return True


class ApprovalLine(models.Model):
    _inherit = 'iatf.approval.line'

    company_id = fields.Many2one(related='request_id.company_id', store=True, readonly=True)

    def _check_access(self, operation):
        result = super()._check_access(operation)
        if result or self.env.su:
            return result
        for line in self.sudo():
            request = self.env['iatf.approval.request'].browse(line.request_id.id)
            if not request.has_access('read' if operation == 'read' else 'write'):
                return self.browse(line.id), lambda: AccessError(_('결재 대상 문서 접근 권한이 없습니다.'))
        return None

    def _search(self, domain, offset=0, limit=None, order=None):
        if not self.env.su:
            allowed = self.env['iatf.approval.request'].search([]).ids
            domain = expression.AND([domain, [('request_id', 'in', allowed)]])
        return super()._search(domain, offset=offset, limit=limit, order=order)

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['request_id', 'state', 'action_date', 'note', 'company_id'])
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            effective = dict(defaults, **vals)
            if _is_internal(self.env):
                # Defaults are caller input, even when a trusted service creates
                # replacement lines. Creation never records an approval verdict.
                vals.update(state='new', action_date=False, note=vals.get('note', False))
                effective.update(vals)
            request = self.env['iatf.approval.request'].browse(effective.get('request_id'))
            request._check_target(current=not _is_internal(self.env))
            if not _is_internal(self.env):
                if (request.state != 'draft' or effective.get('state', 'new') != 'new'
                        or effective.get('action_date') or effective.get('company_id')):
                    raise UserError(_('상신한 결재선이나 승인 결과를 직접 생성할 수 없습니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if not _is_internal(self.env):
            if {'request_id', 'state', 'action_date', 'company_id', 'is_current'} & vals.keys():
                raise UserError(_('결재선의 대상과 승인 결과는 직접 바꿀 수 없습니다.'))
            for line in self:
                line.request_id._check_target()
                if vals and line.request_id.state != 'draft':
                    raise UserError(_('상신한 결재선은 변경할 수 없습니다.'))
        return super().write(vals)

    def unlink(self):
        for line in self:
            line.request_id._check_target()
            if line.request_id.state != 'draft':
                raise UserError(_('상신한 결재선과 처리 이력은 삭제할 수 없습니다.'))
        # Draft-line editing is part of the existing document UI. Its target
        # write right was checked above; ACL elevation is restricted to deletion.
        return super(ApprovalLine, self.sudo()).unlink()


class ApprovalMixin(models.AbstractModel):
    _inherit = 'iatf.approval.mixin'

    approval_current_line_id = fields.Many2one(
        related='approval_request_id.current_line_id', readonly=True)

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        arch, view = super()._get_view(view_id=view_id, view_type=view_type, **options)
        if view_type == 'form':
            arch = deepcopy(arch)
            buttons = arch.xpath("//button[@name='action_approve_approval']")
            for button in buttons:
                # The browser sends the line it displayed, never a freshly read
                # server-side replacement. Existing custom contexts are retained.
                if not button.get('context'):
                    button.set('context', "{'approval_expected_line_id': approval_current_line_id}")
            if buttons and not arch.xpath("//field[@name='approval_current_line_id']"):
                etree.SubElement(arch, 'field', name='approval_current_line_id', invisible='1')
        return arch, view

    approval_state = fields.Selection([
        ('draft', 'Draft'), ('in_progress', 'In Progress'),
        ('approved', 'Approved'), ('rejected', 'Rejected')],
        related=False, compute='_compute_guarded_approval_state', store=True, readonly=True)

    @api.depends('approval_request_id.state', 'approval_request_id.guard_version')
    def _compute_guarded_approval_state(self):
        for record in self:
            request = record.approval_request_id
            # Preserve raw legacy request history, but do not expose it as an
            # executable approval on the target document until freshly reviewed.
            record.approval_state = (request.state if request.guard_version == 1 else 'draft') if request else False

    def _approval_lock_target(self):
        self.check_access('write')
        if self.ids:
            self.flush_recordset()
            self.env.cr.execute(SQL('UPDATE %s SET write_date = write_date WHERE id IN %s',
                                    SQL.identifier(self._table), tuple(sorted(self.ids))))

    def _approval_bind_request(self, request):
        self.ensure_one()
        self.check_access('write')
        if request.res_model != self._name or request.res_id != self.id:
            raise UserError(_('해당 문서의 결재 요청만 연결할 수 있습니다.'))
        _internal(self).write({'approval_request_id': request.id})

    def _approval_ensure_request(self):
        for record in self:
            if not record.approval_request_id:
                request = _internal(self.env['iatf.approval.request']).create({
                    'res_model': record._name, 'res_id': record.id})
                record._approval_bind_request(request)

    def _approval_new_revision(self, previous):
        self.ensure_one()
        self.check_access('write')
        if self.approval_request_id != previous:
            raise UserError(_('현재 결재를 기준으로만 새 결재를 만들 수 있습니다.'))
        request = _internal(self.env['iatf.approval.request']).create({
            'res_model': self._name, 'res_id': self.id, 'previous_request_id': previous.id})
        self._approval_bind_request(request)
        request.write({'line_ids': [(0, 0, {'sequence': line.sequence, 'user_id': line.user_id.id})
                                    for line in previous.line_ids]})
        previous._clear_activities(self)
        self.message_post(body=_('이전 결재 #%s를 보존하고 새 결재를 생성했습니다.') % previous.id)
        return request

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        for vals in vals_list:
            if not _is_internal(self.env):
                for field in _MIXIN_PROTECTED:
                    if vals.get(field, self.env.context.get('default_' + field)):
                        raise UserError(_('승인 연결과 결과를 직접 지정할 수 없습니다.'))
            if 'approval_line_ids' not in vals and 'default_approval_line_ids' in self.env.context:
                vals['approval_line_ids'] = self.env.context['default_approval_line_ids']
        with self.env.cr.savepoint():
            return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if not _is_internal(self.env) and _MIXIN_PROTECTED & vals.keys():
            raise UserError(_('승인 연결과 결과는 결재 절차에서만 변경합니다.'))
        if _is_internal(self.env):
            return super().write(vals)
        with self.env.cr.savepoint():
            self._approval_lock_target()
            active = {r.id: r.approval_request_id for r in self if r.approval_state == 'in_progress'}
            result = super().write(vals)
            if self._approval_should_reset(vals):
                for record in self:
                    previous = active.get(record.id)
                    if previous and record.approval_request_id == previous:
                        record._approval_new_revision(previous)
            return result

    def unlink(self):
        self.check_access('unlink')
        requests = self.env['iatf.approval.request'].sudo().search([
            ('res_model', '=', self._name), ('res_id', 'in', self.ids)])
        if any(request.state != 'draft' for request in requests):
            raise UserError(_('상신·승인·반려 이력이 있는 문서는 삭제하지 않고 정정하세요.'))
        return super().unlink()

    def _approval_check_approved(self, action_label=None):
        super()._approval_check_approved(action_label)
        for record in self:
            request = record.approval_request_id
            request._check_target(operation='read')
            if (request.guard_version != 1 or not request.approved_date or not request.line_ids
                    or any(line.state != 'approved' or not line.action_date for line in request.line_ids)):
                raise UserError(_('검증된 승인 근거가 없습니다. 기존 자료는 새 결재 검토가 필요합니다.'))
