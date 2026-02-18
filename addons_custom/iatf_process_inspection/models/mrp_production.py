from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    pqc_inspection_ids = fields.One2many(
        "iatf.process.inspection", "production_id", string="공정검사",
    )
    pqc_count = fields.Integer(compute="_compute_pqc_count")

    def _compute_pqc_count(self):
        for rec in self:
            rec.pqc_count = len(rec.pqc_inspection_ids)

    def button_mark_done(self):
        res = super().button_mark_done()
        for production in self:
            if production.state == "done":
                production._create_pqc_inspection()
        return res

    def _create_pqc_inspection(self):
        """제조오더 완료 시 최종검사(FQC) 레코드 자동 생성"""
        PQC = self.env["iatf.process.inspection"]
        vals = {
            "inspection_stage": "final",
            "production_id": self.id,
            "product_id": self.product_id.id,
            "lot_id": self.lot_producing_id.id if self.lot_producing_id else False,
            "workcenter_id": self.workcenter_id.id if hasattr(self, "workcenter_id") and self.workcenter_id else False,
            "quantity_produced": self.qty_produced,
            "quantity_inspected": self.qty_produced,
        }
        pqc = PQC.create(vals)
        _logger.info("PQC auto-created: %s for MO %s, product %s",
                     pqc.name, self.name, self.product_id.name)

    def action_view_pqc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.process.inspection",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "name": _("공정검사"),
            "context": {"default_production_id": self.id},
        }
