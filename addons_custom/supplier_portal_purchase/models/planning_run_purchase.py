from odoo import api, fields, models, _


class InjectionPlanningRun(models.Model):
    """생산계획에 발주 연결 필드 추가 (조회용)"""
    _inherit = "injection.planning.run"

    # 기존 연결된 발주서 조회용 (외주 계획에서 생성된 발주와 구분)
    purchase_order_ids = fields.One2many(
        "purchase.order",
        "planning_run_id",
        string="연결된 발주",
    )
    purchase_order_count = fields.Integer(
        string="발주 건수",
        compute="_compute_purchase_order_count",
    )

    @api.depends("purchase_order_ids")
    def _compute_purchase_order_count(self):
        for run in self:
            run.purchase_order_count = len(run.purchase_order_ids)

    def action_view_purchase_orders(self):
        """연결된 발주서 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("연결된 발주"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("planning_run_id", "=", self.id)],
        }
