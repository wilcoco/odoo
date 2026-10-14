from odoo import models, _
from .traceability_record import _TRACE_TOKEN


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        result = super()._action_done(cancel_backorder=cancel_backorder)
        for move in result.filtered(lambda record: record.state == 'done'):
            move._create_traceability_record()
        return result

    def _create_traceability_record(self):
        """One immutable source-linked row per actual tracked stock move line."""
        Trace = self.env['iatf.traceability.record'].sudo().with_context(_iatf_trace_token=_TRACE_TOKEN)
        for move in self.filtered(lambda record: record.state == 'done'):
            for line in move.move_line_ids.filtered(lambda row: row.lot_id and row.quantity):
                if Trace.search_count([('move_line_id', '=', line.id)], limit=1):
                    continue
                production = move.production_id or move.raw_material_production_id
                vals = {'product_id': line.product_id.id, 'lot_id': line.lot_id.id,
                        'quantity': line.product_uom_id._compute_quantity(line.quantity, line.product_id.uom_id, round=False),
                        'quantity_uom_id': line.product_id.uom_id.id, 'company_id': line.company_id.id,
                        'move_line_id': line.id, 'record_date': line.date,
                        'process_step': _('%s → %s') % (line.location_id.complete_name, line.location_dest_id.complete_name),
                        'production_id': production.id or False}
                if move.production_id:
                    vals['input_lot_ids'] = [(6, 0, production.move_raw_ids.filtered(
                        lambda raw: raw.state == 'done').move_line_ids.lot_id.ids)]
                Trace.with_company(line.company_id).create(vals)
