from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    iqc_inspection_ids = fields.One2many(
        "iatf.incoming.inspection", "picking_id", string="수입검사",
    )
    iqc_count = fields.Integer(compute="_compute_iqc_count")

    def _compute_iqc_count(self):
        for rec in self:
            rec.iqc_count = len(rec.iqc_inspection_ids)

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.picking_type_code == "incoming" and picking.state == "done":
                picking._create_iqc_inspections()
        return res

    def _create_iqc_inspections(self):
        """입고 완료 시 제품별 수입검사 레코드 자동 생성"""
        IQC = self.env["iatf.incoming.inspection"]
        for move in self.move_ids.filtered(lambda m: m.state == "done" and m.product_id.type != "service"):
            supplier = self.partner_id
            if not supplier:
                continue
            vals = {
                "picking_id": self.id,
                "purchase_id": self.origin and self._get_purchase_order_id() or False,
                "supplier_id": supplier.id,
                "product_id": move.product_id.id,
                "lot_id": move.lot_ids[:1].id if move.lot_ids else False,
                "quantity_received": move.quantity,
                "quantity_inspected": move.quantity,
                "inspection_type": "sampling",
            }
            iqc = IQC.create(vals)
            _logger.info("IQC auto-created: %s for picking %s, product %s",
                         iqc.name, self.name, move.product_id.name)

    def _get_purchase_order_id(self):
        """origin 필드에서 PO 찾기"""
        if self.origin:
            po = self.env["purchase.order"].search([("name", "=", self.origin)], limit=1)
            return po.id if po else False
        return False

    def action_view_iqc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.incoming.inspection",
            "view_mode": "list,form",
            "domain": [("picking_id", "=", self.id)],
            "name": _("수입검사"),
            "context": {"default_picking_id": self.id},
        }
