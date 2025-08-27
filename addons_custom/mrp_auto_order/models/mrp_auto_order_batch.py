# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools.safe_eval import safe_eval


class MrpAutoOrderBatch(models.Model):
    _name = 'mrp.auto.order.batch'
    _description = 'Batch record for auto-created Manufacturing Orders'
    _order = 'id desc'

    name = fields.Char(string='Name', default=lambda self: self._default_name(), readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    picking_type_id = fields.Many2one('stock.picking.type', string='Operation Type')
    plan_now = fields.Boolean(string='Plan after Confirm')
    origin_prefix = fields.Char(string='Origin Prefix')

    line_ids = fields.One2many('mrp.auto.order.batch.line', 'batch_id', string='Lines')

    created_mo_count = fields.Integer(string='Created MO Count', compute='_compute_created_mo_count', store=False)

    @api.model
    def _default_name(self):
        now = fields.Datetime.now()
        return _('MO Auto Batch %s') % fields.Datetime.to_string(now)

    @api.depends('line_ids.mo_id', 'line_ids.status')
    def _compute_created_mo_count(self):
        for rec in self:
            rec.created_mo_count = len(rec.line_ids.filtered(lambda l: l.status == 'created' and l.mo_id))

    def action_view_created_mos(self):
        self.ensure_one()
        mo_ids = self.line_ids.mapped('mo_id').ids
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_production_action")
        action['domain'] = [('id', 'in', mo_ids)] if mo_ids else [('id', '=', 0)]
        # Merge context with batch company to avoid multi-company filtering issues
        raw_ctx = action.get('context') or {}
        if isinstance(raw_ctx, str):
            try:
                raw_ctx = safe_eval(raw_ctx)
            except Exception:
                raw_ctx = {}
        action_ctx = dict(raw_ctx)
        action_ctx['default_company_id'] = self.company_id.id
        action_ctx['allowed_company_ids'] = [self.company_id.id]
        action['context'] = action_ctx
        return action


class MrpAutoOrderBatchLine(models.Model):
    _name = 'mrp.auto.order.batch.line'
    _description = 'Line in MO Auto Batch'
    _order = 'id asc'

    batch_id = fields.Many2one('mrp.auto.order.batch', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    product_qty = fields.Float(string='Quantity', required=True)
    origin = fields.Char(string='Origin')

    status = fields.Selection([('draft', 'Draft'),
                               ('existing', 'Existing'),
                               ('created', 'Created'),
                               ('error', 'Error')],
                              string='Status', default='draft')
    message = fields.Text(string='Message')

    mo_id = fields.Many2one('mrp.production', string='Manufacturing Order')
