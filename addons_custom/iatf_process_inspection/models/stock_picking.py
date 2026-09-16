from odoo import api, fields, models, _
from odoo.exceptions import UserError
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
        self.check_access("write")
        # 출하 시 OQC 자동 생성
        created = False
        for picking in self:
            if picking.picking_type_code == "outgoing" and not picking.sudo().oqc_inspection_ids:
                picking.sudo()._create_oqc_inspections()
                created = True
        if created:
            # Raising here would roll back the new inspections on every retry.
            return {
                "type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("출하검사 대기"), "message": _("출하검사를 생성했습니다. 품질 담당자의 판정과 승인 후 다시 출하해 주세요."), "type": "warning", "sticky": True},
            }
        self._check_oqc_release()
        return super().button_validate()

    def _check_oqc_release(self):
        """Validate again at stock completion, including wizard/internal routes."""
        for picking in self.filtered(lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")):
            inspections = picking.sudo().oqc_inspection_ids
            if not inspections:
                raise UserError(_("출하검사(OQC)가 없어 출하할 수 없습니다."))
            products = picking.move_ids.filtered(lambda m: m.state != "cancel" and m.product_id.type != "service").product_id
            if products - inspections.product_id:
                raise UserError(_("출하 품목에 대한 출하검사(OQC)가 누락되었습니다."))
            invalid = inspections.filtered(lambda r: (
                r.inspection_stage != "oqc" or r.company_id != picking.company_id
                or r.state not in ("decided", "closed")
                or r.result not in ("pass", "conditional")
                or r.disposition not in ("ship", "concession")
            ))
            if invalid:
                raise UserError(_("출하검사(OQC)의 합격 판정과 출하 처분을 확인해 주세요: %s") % ", ".join(invalid.mapped("name")))
            inspections._approval_check_approved(_("출하"))

    def _action_done(self):
        self._check_oqc_release()
        return super()._action_done()

    def _create_oqc_inspections(self):
        """출하 확정 시 제품별 출하검사(OQC) 레코드 자동 생성"""
        PQC = self.env["iatf.process.inspection"]
        for move in self.move_ids.filtered(lambda m: m.product_id.type != "service"):
            vals = {
                "company_id": self.company_id.id,
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


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        self.filtered(lambda m: m.state not in ("done", "cancel")).picking_id._check_oqc_release()
        return super()._action_done(cancel_backorder=cancel_backorder)
