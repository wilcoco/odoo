from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    car_model_id = fields.Many2one(
        "engel.car.model", string="차종", tracking=True,
    )

    injection_serial_ids = fields.One2many(
        "engel.injection.serial", "production_id", string="사출 시리얼",
    )
    injection_serial_count = fields.Integer(
        string="시리얼 수",
        compute="_compute_injection_stats",
        store=True,
    )
    injection_ok_count = fields.Integer(
        string="합격 수",
        compute="_compute_injection_stats",
        store=True,
    )
    injection_ng_count = fields.Integer(
        string="불합격 수",
        compute="_compute_injection_stats",
        store=True,
    )
    injection_defect_rate = fields.Float(
        string="불량률 (%)",
        compute="_compute_injection_stats",
        store=True,
    )

    @api.depends("injection_serial_ids", "injection_serial_ids.qc_result")
    def _compute_injection_stats(self):
        for rec in self:
            serials = rec.injection_serial_ids
            total = len(serials)
            ok = len(serials.filtered(lambda s: s.qc_result == "ok"))
            ng = total - ok
            rec.injection_serial_count = total
            rec.injection_ok_count = ok
            rec.injection_ng_count = ng
            rec.injection_defect_rate = (ng / total * 100.0) if total else 0.0

    def action_view_injection_serials(self):
        """사출 시리얼 레코드 목록 열기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "engel.injection.serial",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "name": _("사출 시리얼"),
            "context": {
                "default_production_id": self.id,
                "default_product_id": self.product_id.id,
                "default_car_model_id": self.car_model_id.id if self.car_model_id else False,
                "default_mold_id": self.mold_id.id if self.mold_id else False,
            },
        }

    def _update_mold_shots(self):
        """금형 샷카운트: 사출 시리얼이 이미 추적한 경우 중복 방지"""
        if self.injection_serial_ids:
            _logger.info(
                "Skipping bulk mold shot update for MO %s "
                "— shots already tracked via injection serials",
                self.name,
            )
            return
        return super()._update_mold_shots()
