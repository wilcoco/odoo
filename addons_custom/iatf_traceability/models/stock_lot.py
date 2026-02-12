from odoo import fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    traceability_record_ids = fields.One2many(
        "iatf.traceability.record", "lot_id", string="Traceability Records",
    )
    traceability_record_count = fields.Integer(
        compute="_compute_traceability_record_count", string="Trace Records",
    )

    def _compute_traceability_record_count(self):
        for lot in self:
            lot.traceability_record_count = len(lot.traceability_record_ids)

    def action_view_traceability_records(self):
        self.ensure_one()
        return {
            "name": "Traceability Records",
            "type": "ir.actions.act_window",
            "res_model": "iatf.traceability.record",
            "view_mode": "list,form",
            "domain": [("lot_id", "=", self.id)],
            "context": {"default_lot_id": self.id, "default_product_id": self.product_id.id},
        }
