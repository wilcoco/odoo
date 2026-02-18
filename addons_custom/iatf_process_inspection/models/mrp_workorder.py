from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    ipqc_inspection_ids = fields.One2many(
        "iatf.process.inspection", "workorder_id", string="공정검사",
    )
    ipqc_count = fields.Integer(compute="_compute_ipqc_count")

    def _compute_ipqc_count(self):
        for rec in self:
            rec.ipqc_count = len(rec.ipqc_inspection_ids)

    def button_finish(self):
        res = super().button_finish()
        for wo in self:
            if wo.state == "done":
                wo._create_ipqc_inspection()
        return res

    def _create_ipqc_inspection(self):
        """작업지시 완료 시 IPQC 자동 생성"""
        PQC = self.env["iatf.process.inspection"]
        vals = {
            "inspection_stage": "ipqc",
            "production_id": self.production_id.id,
            "workorder_id": self.id,
            "workcenter_id": self.workcenter_id.id,
            "product_id": self.product_id.id,
            "lot_id": self.lot_id.id if self.lot_id else (
                self.production_id.lot_producing_id.id if self.production_id.lot_producing_id else False),
            "quantity_produced": self.qty_produced,
            "quantity_inspected": self.qty_produced,
        }
        ipqc = PQC.create(vals)
        _logger.info("IPQC auto-created: %s for WO %s, workcenter %s",
                     ipqc.name, self.name, self.workcenter_id.name)

    def action_view_ipqc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.process.inspection",
            "view_mode": "list,form",
            "domain": [("workorder_id", "=", self.id)],
            "name": _("공정검사"),
            "context": {"default_workorder_id": self.id, "default_inspection_stage": "ipqc"},
        }
