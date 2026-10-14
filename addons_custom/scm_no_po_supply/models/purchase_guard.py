"""Opt-in component scope cannot generate new purchase demand in parallel.

Already confirmed POs and all products without an active agreement retain the
original receiving path. No prices, resin policy, or settlement entries change.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .supply_notice import lock_supply_scopes


def check_no_po_conflict(env, company, partner, products, date):
    if not products:
        return
    lock_supply_scopes(env, company, partner, products)
    # Purchase clerks can read company-scoped agreements. No privilege elevation.
    agreements = env['scm.no.po.agreement'].search([
        ('company_id', '=', company.id), ('partner_id', '=', partner.commercial_partner_id.id),
        ('product_id', 'in', products.ids), ('active', '=', True),
        ('date_start', '<=', date), '|', ('date_end', '=', False), ('date_end', '>=', date)], limit=1)
    if agreements:
        raise UserError(_('활성 무발주 부품 협약 대상입니다. 새 발주 대신 수량 요구통보를 작성하세요: %s') % agreements.product_id.display_name)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            order = self.env['purchase.order'].browse(values.get('order_id', self.env.context.get('default_order_id')))
            product = self.env['product.product'].browse(values.get('product_id'))
            if order and product:
                check_no_po_conflict(self.env, order.company_id, order.partner_id, product,
                    fields.Date.to_date(values.get('date_planned')) or fields.Date.context_today(order))
        return super().create(vals_list)

    def write(self, vals):
        guarded = {'order_id', 'product_id', 'product_qty', 'product_uom', 'date_planned'}
        if set(vals) & guarded:
            for line in self.filtered(lambda rec: not rec.display_type):
                order = self.env['purchase.order'].browse(vals.get('order_id')) or line.order_id
                product = self.env['product.product'].browse(vals.get('product_id')) or line.product_id
                planned = (fields.Date.to_date(vals.get('date_planned'))
                    or fields.Date.to_date(line.date_planned) or fields.Date.context_today(order))
                if order and product:
                    check_no_po_conflict(
                        self.env, order.company_id, order.partner_id, product, planned)
        return super().write(vals)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _check_no_po_supply_conflict(self, partner=None, company=None):
        for order in self:
            effective_partner = partner or order.partner_id
            effective_company = company or order.company_id
            for line in order.order_line.filtered(lambda rec: not rec.display_type):
                check_no_po_conflict(
                    self.env, effective_company, effective_partner, line.product_id,
                    fields.Date.to_date(line.date_planned) or fields.Date.context_today(order))

    def button_confirm(self):
        for order in self.filtered(lambda o: o.state in ('draft', 'sent', 'to approve')):
            order._check_no_po_supply_conflict()
        return super().button_confirm()

    def button_approve(self, force=False):
        self._check_no_po_supply_conflict()
        return super().button_approve(force=force)

    def write(self, vals):
        if set(vals) & {'partner_id', 'company_id'}:
            partner = self.env['res.partner'].browse(vals.get('partner_id')) if vals.get('partner_id') else None
            company = self.env['res.company'].browse(vals.get('company_id')) if vals.get('company_id') else None
            self._check_no_po_supply_conflict(partner=partner, company=company)
        return super().write(vals)


class OutsourcePlanningRun(models.Model):
    _inherit = 'outsource.planning.run'

    def _create_purchase_order(self, partner_id, lines):
        partner = self.env['res.partner'].browse(partner_id)
        for line in lines:
            check_no_po_conflict(self.env, self.env.company, partner, line.product_id,
                line.demand_date or fields.Date.context_today(self))
        return super()._create_purchase_order(partner_id, lines)
