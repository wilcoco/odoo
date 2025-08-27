# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
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

    def action_process_batch(self):
        self.ensure_one()
        created_mos = self.env['mrp.production']
        existing_mos = self.env['mrp.production']
        ctx = dict(self._context or {})
        # Determine manufacturing picking type: use selected or fallback to an active manufacturing type for the company
        picking_type = self.picking_type_id
        if not picking_type:
            picking_type = self.env['stock.picking.type'].search([
                ('code', '=', 'mrp_operation'),
                ('active', '=', True),
                ('company_id', 'in', [self.company_id.id, False]),
            ], order='company_id desc, id asc', limit=1)
        if picking_type:
            ctx['default_picking_type_id'] = picking_type.id
        ctx['allowed_company_ids'] = [self.company_id.id]

        draft_lines = self.line_ids.filtered(lambda l: l.status == 'draft')
        if not draft_lines:
            raise UserError(_('No draft lines to process in this batch.'))

        errors = []
        for line in draft_lines:
            # validations
            if not line.product_id:
                msg = _('Missing product on a line. Please select a product.')
                line.write({'status': 'error', 'message': msg})
                errors.append(msg)
                continue
            if line.product_id.type == 'service':
                msg = _('"%s" is a service product and cannot be manufactured.') % line.product_id.display_name
                line.write({'status': 'error', 'message': msg})
                errors.append(msg)
                continue
            if line.product_qty <= 0:
                msg = _('Quantity must be strictly positive for "%s".') % line.product_id.display_name
                line.write({'status': 'error', 'message': msg})
                errors.append(msg)
                continue

            # origin composition (batch prefix + line origin)
            origin_val = (self.origin_prefix or '')
            if line.origin:
                origin_val = (origin_val + ' ' + line.origin).strip()
            elif origin_val:
                origin_val = origin_val.strip()

            # find existing MO
            domain = [
                ('company_id', '=', self.company_id.id),
                ('product_id', '=', line.product_id.id),
                ('origin', '=', origin_val),
                ('state', '!=', 'cancel'),
            ]
            existing_mo = self.env['mrp.production'].with_context(ctx).search(domain, limit=1, order='id desc')
            if existing_mo:
                line.write({
                    'status': 'existing',
                    'mo_id': existing_mo.id,
                    'message': _('Existing MO matched by origin and product.'),
                })
                existing_mos |= existing_mo
                continue

            # create new MO
            mo_vals = {
                'product_id': line.product_id.id,
                'product_qty': line.product_qty,
                'company_id': self.company_id.id,
            }
            if origin_val:
                mo_vals['origin'] = origin_val
            if picking_type:
                mo_vals['picking_type_id'] = picking_type.id

            mo = self.env['mrp.production'].with_context(ctx).create(mo_vals)
            # ensure BoM link for proper WO generation
            if mo.bom_id:
                try:
                    mo._link_bom(mo.bom_id)
                except Exception as e:
                    msg = _('Failed to link BoM for "%(product)s": %(error)s') % {
                        'product': line.product_id.display_name,
                        'error': str(e),
                    }
                    errors.append(msg)
                    line.message = msg

            try:
                if not mo.bom_id:
                    msg = _('No Bill of Materials found for "%s". MO kept as Draft (Origin: %s).') % (
                        line.product_id.display_name, origin_val or '-')
                    errors.append(msg)
                    line.write({'status': 'created', 'mo_id': mo.id, 'message': msg})
                    created_mos |= mo
                    continue
                if self.plan_now:
                    mo.action_plan_with_components_availability()
                else:
                    mo.action_confirm()
                line.write({'status': 'created', 'mo_id': mo.id, 'message': _('MO created successfully.')})
            except Exception as e:
                msg = _('Failed to confirm/plan MO for "%(product)s": %(error)s') % {
                    'product': line.product_id.display_name,
                    'error': str(e),
                }
                errors.append(msg)
                line.write({'status': 'error', 'mo_id': mo.id, 'message': msg})
            created_mos |= mo

        # build and return action to display resulting MOs
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_production_action")
        mo_show = (created_mos | existing_mos)
        action['domain'] = [('id', 'in', mo_show.ids)] if mo_show else [('id', '=', 0)]
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

    @api.model
    def cron_process_pending_batches(self, limit=20):
        """Cron job entrypoint: process batches having draft lines.
        - Processes up to `limit` batches per run to avoid long transactions.
        - Respects each batch's company and picking type context.
        - Only processes batches that still have at least one draft line.
        """
        # Find candidate batches via their draft lines, prioritize newest first
        Line = self.env['mrp.auto.order.batch.line']
        draft_lines = Line.search([('status', '=', 'draft')], order='id desc', limit=limit)
        if not draft_lines:
            return
        batch_ids = draft_lines.mapped('batch_id').ids
        batches = self.browse(batch_ids)
        for batch in batches:
            # Process each batch in its company context
            ctx = dict(self.env.context, allowed_company_ids=[batch.company_id.id])
            try:
                batch.with_context(ctx).action_process_batch()
            except Exception as e:
                # Log and continue without raising to keep cron robust
                _logger = self.env['ir.logging']
                try:
                    _logger.create({
                        'name': 'mrp_auto_order.cron',
                        'type': 'server',
                        'dbname': self._cr.dbname,
                        'level': 'ERROR',
                        'message': f'Batch {batch.id} processing failed: {e}',
                        'path': __name__,
                        'func': 'cron_process_pending_batches',
                        'line': '0',
                    })
                except Exception:
                    # Swallow logging errors
                    pass

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
