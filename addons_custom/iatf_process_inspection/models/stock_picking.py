from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    oqc_inspection_ids = fields.One2many(
        "iatf.process.inspection", "picking_id", string="출하검사",
    )
    oqc_count = fields.Integer(compute="_compute_oqc_count")

    def _compute_oqc_count(self):
        for rec in self:
            rec.oqc_count = len(rec.oqc_inspection_ids)

    def button_validate(self):
        from odoo.exceptions import UserError as UE
        # 출하 시 OQC 자동 생성
        for picking in self:
            if picking.picking_type_code == "outgoing" and not picking.oqc_inspection_ids:
                picking._create_oqc_inspections()
            # OQC 합격 전 출하 차단 (L3-2)
            if picking.picking_type_code == "outgoing" and picking.oqc_inspection_ids:
                pending = picking.oqc_inspection_ids.filtered(
                    lambda r: r.state not in ("decided", "closed") or not r.result)
                if pending:
                    raise UE(_(
                        "출하검사(OQC) 판정이 완료되지 않았습니다.\n"
                        "미완료 검사: %s") % ", ".join(pending.mapped("name")))
                failed = picking.oqc_inspection_ids.filtered(lambda r: r.result == "fail")
                if failed:
                    raise UE(_(
                        "출하검사(OQC) 불합격 건이 있어 출하할 수 없습니다.\n"
                        "불합격 검사: %s") % ", ".join(failed.mapped("name")))
        return super().button_validate()

    def _create_oqc_inspections(self):
        """출하 확정 시 제품별 출하검사(OQC) 레코드 자동 생성"""
        PQC = self.env["iatf.process.inspection"]
        for move in self.move_ids.filtered(lambda m: m.product_id.type != "service"):
            vals = {
                "inspection_stage": "oqc",
                "picking_id": self.id,
                "product_id": move.product_id.id,
                "lot_id": move.lot_ids[:1].id if move.lot_ids else False,
                "quantity_produced": move.product_uom_qty,
                "quantity_inspected": move.product_uom_qty,
            }
            oqc = PQC.create(vals)
            _logger.info("OQC auto-created: %s for outgoing picking %s, product %s",
                         oqc.name, self.name, move.product_id.name)

    def action_view_oqc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.process.inspection",
            "view_mode": "list,form",
            "domain": [("picking_id", "=", self.id)],
            "name": _("출하검사"),
            "context": {"default_picking_id": self.id, "default_inspection_stage": "oqc"},
        }
