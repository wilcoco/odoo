# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class MrpAutoOrderWizard(models.TransientModel):
    _name = 'mrp.auto.order.wizard'
    _description = 'Auto-create Manufacturing Orders from an order list'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    picking_type_id = fields.Many2one(
        'stock.picking.type', string='Operation Type',
        domain="[('code', '=', 'mrp_operation')]",
        help='Optional. If set, BOM search and MO picking type will use this operation type.')
    plan_now = fields.Boolean(
        string='Plan after Confirm', default=True,
        help='If enabled, the wizard will plan work orders after confirming the MO '
             '(uses action_plan_with_components_availability).')
    origin_prefix = fields.Char(
        string='Origin Prefix',
        help='Optional prefix to add to MO origin (e.g., external order number prefix).')

    line_ids = fields.One2many(
        'mrp.auto.order.wizard.line', 'wizard_id', string='Order Lines',
        help='Each line will create one Manufacturing Order.')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'company_id' in fields_list and not vals.get('company_id'):
            vals['company_id'] = self.env.company.id
        return vals

    def action_process_orders(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Please add at least one order line.'))

        created_mos = self.env['mrp.production']
        ctx = dict(self._context or {})
        if self.picking_type_id:
            ctx['default_picking_type_id'] = self.picking_type_id.id
        # Make sure precompute (e.g., bom_id) and searches run in the selected company
        ctx['allowed_company_ids'] = [self.company_id.id]

        errors = []
        for line in self.line_ids:
            if not line.product_id:
                errors.append(_('Missing product on a line. Please select a product.'))
                continue
            if line.product_id.type == 'service':
                errors.append(_('"%s" is a service product and cannot be manufactured.') % line.product_id.display_name)
                continue
            if line.product_qty <= 0:
                errors.append(_('Quantity must be strictly positive for "%s".') % line.product_id.display_name)
                continue

            origin_val = (self.origin_prefix or '')
            if line.origin:
                origin_val = (origin_val + ' ' + line.origin).strip()
            elif origin_val:
                origin_val = origin_val.strip()

            mo_vals = {
                'product_id': line.product_id.id,
                'product_qty': line.product_qty,
                'company_id': self.company_id.id,
            }
            if origin_val:
                mo_vals['origin'] = origin_val
            if self.picking_type_id:
                mo_vals['picking_type_id'] = self.picking_type_id.id

            mo = self.env['mrp.production'].with_context(ctx).create(mo_vals)
            try:
                # Guard: ensure a BoM was found; otherwise keep MO in draft and report
                if not mo.bom_id:
                    errors.append(_('No Bill of Materials found for "%s". MO kept as Draft (Origin: %s).') % (
                        line.product_id.display_name, origin_val or '-'))
                    created_mos |= mo
                    continue
                if self.plan_now:
                    mo.action_plan_with_components_availability()
                else:
                    mo.action_confirm()
            except Exception as e:
                # keep MO but log error
                errors.append(_('Failed to confirm/plan MO for "%(product)s": %(error)s') % {
                    'product': line.product_id.display_name,
                    'error': str(e),
                })
            created_mos |= mo

        if not created_mos:
            raise UserError(_('No Manufacturing Orders were created.\n\nErrors:\n- %s') % ('\n- '.join(errors) if errors else _('No lines processed')))

        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_production_action")
        action['domain'] = [('id', 'in', created_mos.ids)]
        # Pass a note via context for optional display
        action_ctx = dict(action.get('context', {}) or {})
        if errors:
            action_ctx['mrp_auto_order_wizard_errors'] = errors
        action['context'] = action_ctx
        return action


class MrpAutoOrderWizardLine(models.TransientModel):
    _name = 'mrp.auto.order.wizard.line'
    _description = 'Order line for auto MO creation'

    wizard_id = fields.Many2one('mrp.auto.order.wizard', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('type', 'in', ('consu', 'product'))]")
    product_qty = fields.Float(string='Quantity To Produce', required=True, default=1.0)
    origin = fields.Char(string='Origin')
