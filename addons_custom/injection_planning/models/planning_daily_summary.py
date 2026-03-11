from odoo import api, fields, models


class PlanningDailySummary(models.Model):
    _name = "injection.planning.daily.summary"
    _description = "제품별 일별 생산계획 요약"
    _order = "plan_date, product_id"
    _rec_name = "display_name"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    product_id = fields.Many2one(
        "product.product", string="사출 부품", required=True, index=True,
    )
    plan_date = fields.Date(string="날짜", required=True, index=True)

    # ── 수량 ──
    demand_qty = fields.Float(string="소요량", help="BOM 전개 후 사출 부품 일일 소요량")
    planned_qty = fields.Float(string="생산량", help="해당일 생산 계획량 합계")
    safety_stock_qty = fields.Float(string="안전재고", help="일평균수요 x 안전재고일수")

    # ── 재고 ──
    stock_start = fields.Float(string="시작 재고", help="해당일 시작 시점 예상 재고")
    stock_end = fields.Float(string="종료 재고", help="시작 + 생산 - 소요")

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    @api.depends("product_id", "plan_date")
    def _compute_display_name(self):
        for rec in self:
            pname = rec.product_id.display_name or ""
            dt = str(rec.plan_date) if rec.plan_date else ""
            rec.display_name = f"{pname} / {dt}"
