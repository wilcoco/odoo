from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


_INVOICE_LINK = object()
_TOTALS = {'amount_total', 'amount_tax', 'amount_untaxed'}
_LINE_TOTALS = {'price_subtotal', 'price_tax', 'price_total', 'invoiced'}


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    @api.model
    def _approval_management_roles(self):
        return dict(super()._approval_management_roles(), **{
            'pumui.request': 'pumui_approval.group_pumui_manager',
        })


class PumuiRequest(models.Model):
    _inherit = 'pumui.request'

    @api.depends('move_ids.amount_total', 'move_ids.amount_total_signed', 'move_ids.amount_residual',
                 'move_ids.state', 'move_ids.move_type', 'move_ids.currency_id', 'move_ids.date', 'amount_total')
    def _compute_billing(self):
        for request in self:
            moves = request.move_ids.filtered(lambda m: m.state != 'cancel')
            posted = moves.filtered(lambda m: m.state == 'posted')
            request.move_count = len(moves)
            request.invoiced_amount = sum(m._pumui_company_amount() for m in moves)
            request.paid_amount = sum(m._pumui_company_amount() * (m.amount_total - m.amount_residual) / m.amount_total
                                      for m in posted if m.amount_total)
            remaining = request.amount_total - request.invoiced_amount
            request.uninvoiced_amount = max(remaining, 0.0)
            request.amount_diff = min(remaining, 0.0)
            if not moves:
                request.billing_status = 'none'
            elif request.currency_id.compare_amounts(remaining, 0) > 0:
                request.billing_status = 'partial'
            elif len(posted) == len(moves) and all(m.currency_id.is_zero(m.amount_residual) for m in posted):
                request.billing_status = 'paid'
            else:
                request.billing_status = 'invoiced'

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        for field in _TOTALS:
            vals.pop(field, None)
        return vals

    def _approval_reset_ignored_fields(self):
        return super()._approval_reset_ignored_fields() | {'rejection_reason'}

    def _approval_rejection_reason(self, reason):
        self.ensure_one()
        reason = reason or self.rejection_reason
        if not reason:
            raise UserError(_('반려 사유를 입력해 주세요.'))
        return reason

    @api.model_create_multi
    def create(self, vals_list):
        if any(set(v) & _TOTALS for v in vals_list):
            raise AccessError(_('품의 금액은 항목에서 계산됩니다. 직접 지정할 수 없습니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) & _TOTALS:
            raise AccessError(_('품의 계산 금액은 직접 변경할 수 없습니다.'))
        result = super().write(vals)
        if set(vals) & {'partner_id', 'company_id', 'pumui_type'}:
            self.sudo().move_ids._phase2_check_scope()
        return result

    def _approval_validate_submit(self):
        super()._approval_validate_submit()
        for request in self:
            if not request.line_ids or request.currency_id.compare_amounts(request.amount_total, 0) <= 0:
                raise UserError(_('양수 금액의 품의 항목을 입력한 후 상신해 주세요.'))

    def _approval_snapshot(self):
        self.ensure_one()
        return {
            'model': self._name, 'id': self.id, 'title': self.title,
            'company_id': self.company_id.id, 'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id, 'pumui_type': self.pumui_type,
            'amount_total': self.amount_total,
            'lines': [{'id': l.id, 'name': l.name, 'product_id': l.product_id.id,
                       'quantity': l.quantity, 'price_unit': l.price_unit,
                       'tax_ids': l.tax_ids.ids, 'price_total': l.price_total,
                       'tax_details': [{'id': t.id, 'amount': t.amount, 'amount_type': t.amount_type,
                                        'price_include': t.price_include, 'include_base_amount': t.include_base_amount,
                                        'sequence': t.sequence, 'is_base_affected': t.is_base_affected,
                                        'children_tax_ids': t.children_tax_ids.ids}
                                       for t in (l.tax_ids | l.tax_ids.children_tax_ids).sorted('id')],
                       'payment_stage': l.payment_stage} for l in self.line_ids],
        }

    def action_create_invoice(self, stage=False):
        self.check_access('write')
        self._approval_lock()
        self._approval_check_approved(_('청구서 생성'))
        return super().action_create_invoice(stage=stage)

    def _approval_check_approved(self, action_label=None):
        super()._approval_check_approved(action_label)
        for request in self:
            if request.approval_request_id.snapshot != request._approval_snapshot():
                raise UserError(_('현재 품의 내용과 승인 근거가 다릅니다. 기존 승인은 보존하고 재상신해 주세요.'))
        return True

    def _invalidate_line_approval(self):
        for request in self.filtered(lambda r: r.approval_state in ('approved', 'in_progress')):
            old = request.approval_request_id
            request.action_reset_approval()
            request.message_post(body=_('품의 항목이 변경되어 새 결재 버전이 생성되었습니다. 이전 결재 #%s는 보존됩니다. 재상신해 주세요.') % old.id)


class PumuiLine(models.Model):
    _inherit = 'pumui.request.line'

    @api.depends('quantity', 'price_unit', 'tax_ids', 'tax_ids.amount', 'tax_ids.amount_type',
                 'tax_ids.price_include', 'pumui_id.currency_id', 'pumui_id.partner_id', 'product_id')
    def _compute_price(self):
        return super()._compute_price()

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        for field in _LINE_TOTALS | {'invoice_line_id'}:
            vals.pop(field, None)
        return vals

    def _lock_parents(self, parents):
        parents.check_access('write')
        parents._approval_lock()

    @api.model_create_multi
    def create(self, vals_list):
        if any(set(v) & (_LINE_TOTALS | {'invoice_line_id'}) for v in vals_list):
            raise AccessError(_('계산 금액과 청구 연결은 직접 지정할 수 없습니다.'))
        default_parent = self.default_get(['pumui_id']).get('pumui_id')
        parents = self.env['pumui.request'].browse([
            v.get('pumui_id', default_parent) for v in vals_list if v.get('pumui_id', default_parent)])
        self._lock_parents(parents)
        records = super().create(vals_list)
        records.pumui_id._invalidate_line_approval()
        return records

    def write(self, vals):
        if set(vals) & _LINE_TOTALS:
            raise AccessError(_('품의 항목의 계산 금액은 직접 변경할 수 없습니다.'))
        if 'invoice_line_id' in vals and self.env.context.get('_pumui_invoice_link') is not _INVOICE_LINK:
            raise AccessError(_('청구 연결은 품의 청구서 생성 절차에서만 설정됩니다.'))
        parents = self.pumui_id | self.env['pumui.request'].browse(vals.get('pumui_id', []))
        self._lock_parents(parents)
        if 'pumui_id' in vals and self.filtered('invoice_line_id'):
            raise UserError(_('청구에 연결된 항목은 다른 품의로 이동할 수 없습니다.'))
        result = super().write(vals)
        if set(vals) - {'invoice_line_id'}:
            parents._invalidate_line_approval()
        self._check_invoice_scope()
        return result

    def unlink(self):
        parents = self.pumui_id
        self._lock_parents(parents)
        if self.filtered('invoice_line_id'):
            raise UserError(_('청구에 연결된 품의 항목은 삭제할 수 없습니다.'))
        result = super().unlink()
        parents._invalidate_line_approval()
        return result

    def _link_invoice_line(self, line):
        self.ensure_one()
        return self.with_context(_pumui_invoice_link=_INVOICE_LINK).write({'invoice_line_id': line.id})

    @api.constrains('pumui_id', 'invoice_line_id')
    def _check_invoice_scope(self):
        for line in self.filtered('invoice_line_id'):
            move = line.invoice_line_id.move_id
            if move.pumui_id != line.pumui_id or line.invoice_line_id.display_type != 'product':
                raise ValidationError(_('청구 상세와 품의 상세의 부모가 일치해야 합니다.'))
            move._phase2_check_scope()


class AccountMove(models.Model):
    _inherit = 'account.move'

    pumui_amount_diff = fields.Monetary(currency_field='company_currency_id')

    @api.depends('pumui_id.amount_diff')
    def _compute_pumui_diff(self):
        for move in self:
            move.pumui_amount_diff = move.pumui_id.amount_diff if move.pumui_id else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(v) for v in vals_list]
        for vals in vals_list:
            if vals.get('reversed_entry_id') and vals.get('move_type') in ('in_refund', 'out_refund'):
                source = self.browse(vals['reversed_entry_id'])
                if source.pumui_id:
                    if vals.get('pumui_id') and vals['pumui_id'] != source.pumui_id.id:
                        raise ValidationError(_('환불은 원청구서와 같은 품의에 연결해야 합니다.'))
                    vals['pumui_id'] = source.pumui_id.id
        records = super().create(vals_list)
        records._phase2_check_scope()
        return records

    @api.constrains('pumui_id', 'company_id', 'partner_id', 'move_type', 'reversed_entry_id', 'currency_id')
    def _phase2_check_scope(self):
        for move in self:
            if move.reversed_entry_id.pumui_id and move.move_type.endswith('_refund') and move.pumui_id != move.reversed_entry_id.pumui_id:
                raise ValidationError(_('품의 청구서의 환불은 같은 품의 연결을 유지해야 합니다.'))
        for move in self.filtered('pumui_id'):
            request = move.pumui_id.sudo()
            if move.currency_id.compare_amounts(move.amount_total, 0) < 0:
                raise ValidationError(_('음수 청구서 대신 원청구서에 연결된 환불 문서를 사용해 주세요.'))
            types = ('in_invoice', 'in_refund') if request.pumui_type == 'purchase' else ('out_invoice', 'out_refund')
            if move.move_type not in types or move.company_id != request.company_id or move.partner_id.commercial_partner_id != request.partner_id.commercial_partner_id:
                raise ValidationError(_('청구서와 품의의 유형·회사·거래처가 일치해야 합니다.'))
            if move.move_type.endswith('_refund'):
                source = move.reversed_entry_id
                if not source or source.pumui_id != request or source.move_type != types[0] or source.state != 'posted' or source.currency_id != move.currency_id:
                    raise ValidationError(_('환불에는 같은 품의·통화의 전기된 원청구서가 필요합니다.'))
        linked = self.env['pumui.request.line'].sudo().search([('invoice_line_id.move_id', 'in', self.ids)])
        for line in linked:
            if line.pumui_id != line.invoice_line_id.move_id.pumui_id:
                raise ValidationError(_('품의 항목의 청구 연결을 다른 문서로 옮길 수 없습니다.'))

    def _pumui_company_amount(self):
        self.ensure_one()
        amount = abs(self.amount_total_signed) if self.state == 'posted' else self.currency_id._convert(
            self.amount_total, self.company_id.currency_id, self.company_id,
            self.date or self.invoice_date or fields.Date.context_today(self),
        )
        return -amount if self.move_type.endswith('_refund') else amount

    def _check_pumui_budget(self, requests, candidates=None):
        """Called with the request write fence held, including internal posting."""
        candidates = candidates if candidates is not None else self.browse()
        Move = self.sudo()
        for request in requests.sudo():
            posted = Move.search([('pumui_id', '=', request.id), ('state', '=', 'posted')])
            moves = posted | candidates.filtered(lambda m: m.pumui_id == request and m.state != 'posted')
            total = sum(m._pumui_company_amount() for m in moves)
            currency = request.currency_id
            if currency.compare_amounts(total, request.amount_total) > 0 or currency.compare_amounts(total, 0) < 0:
                raise UserError(_('누적 전기 금액이 품의 승인 한도를 초과하거나 환불액이 원청구액을 초과합니다.'))
            for source in moves.filtered(lambda m: m.move_type.endswith('_refund')).reversed_entry_id:
                credits = moves.filtered(lambda m: m.reversed_entry_id == source)
                if source.currency_id.compare_amounts(sum(credits.mapped('amount_total')), source.amount_total) > 0:
                    raise UserError(_('원청구서 금액을 초과하여 환불할 수 없습니다.'))

    def _post(self, soft=True):
        candidates = self.filtered(lambda m: m.state != 'posted' and m.pumui_id)
        requests = candidates.pumui_id.sudo()
        with self.env.cr.savepoint():
            requests._approval_lock()
            candidates._phase2_check_scope()
            requests._approval_check_approved(_('전기'))
            self._check_pumui_budget(requests, candidates)
            result = super()._post(soft=soft)
            self._check_pumui_budget(requests)
            return result

    def write(self, vals):
        if 'pumui_id' in vals and not vals['pumui_id'] and self.filtered('pumui_id'):
            raise UserError(_('품의 연결을 제거하여 결재 통제를 해제할 수 없습니다.'))
        scope_fields = {'pumui_id', 'reversed_entry_id', 'company_id', 'currency_id', 'partner_id', 'move_type'}
        for move in self.filtered(lambda m: m.state == 'posted' and m.pumui_id):
            for name in set(vals) & scope_fields:
                current = move[name].id if move._fields[name].type == 'many2one' else move[name]
                if current != vals[name]:
                    raise UserError(_('전기된 품의 청구서의 근거 연결·유형·회사·통화·거래처는 변경할 수 없습니다.'))
        if 'pumui_id' in vals and any(m.state != 'draft' and m.pumui_id.id != vals['pumui_id'] for m in self):
            raise UserError(_('전기된 청구서의 품의 연결은 변경할 수 없습니다.'))
        requests = self.pumui_id.sudo() | self.env['pumui.request'].sudo().browse(vals.get('pumui_id', []))
        with self.env.cr.savepoint():
            if requests and set(vals) & {'pumui_id', 'state', 'partner_id', 'company_id', 'currency_id', 'move_type'}:
                requests._approval_lock()
            if vals.get('state') in ('draft', 'cancel'):
                sources = self.filtered(lambda m: m.state == 'posted' and m.pumui_id and not m.move_type.endswith('_refund'))
                if sources and self.sudo().search_count([('reversed_entry_id', 'in', sources.ids), ('state', '=', 'posted')]):
                    raise UserError(_('전기된 환불이 있는 원청구서는 먼저 환불을 정리해야 취소할 수 있습니다.'))
            result = super().write(vals)
            if set(vals) & {'pumui_id', 'partner_id', 'company_id', 'currency_id', 'move_type', 'reversed_entry_id'}:
                self._phase2_check_scope()
            if vals.get('state') in ('draft', 'cancel'):
                self._check_pumui_budget(requests)
            return result


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def write(self, vals):
        result = super().write(vals)
        if set(vals) & {'move_id', 'company_id', 'partner_id', 'display_type'}:
            links = self.env['pumui.request.line'].sudo().search([('invoice_line_id', 'in', self.ids)])
            links._check_invoice_scope()
        return result
