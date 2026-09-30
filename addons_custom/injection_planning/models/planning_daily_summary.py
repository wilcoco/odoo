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
    planned_qty = fields.Float(string="생산량", help="해당일 생산 계획량 합계(총생산량, 불량·초기불량 포함)")
    expected_good_qty = fields.Float(string="예상 양품", help="[R135] (계획 − 초기불량) × (1 − 불량률) 합계. 총생산량과 구별한다.")
    safety_stock_qty = fields.Float(string="안전재고", help="해당 날짜로부터 향후 N일간 실제 수요 합계")

    # ── 재고 ──
    stock_start = fields.Float(string="시작 재고", help="해당일 시작 시점 예상 재고")
    stock_end = fields.Float(string="종료 재고", help="시작 + 생산 - 소요")

    # ── 결품 위기 ──
    shortage_risk = fields.Boolean(
        string="결품 위기",
        compute="_compute_shortage_risk",
        store=True,
        help="종료 재고가 안전재고 미만이면 결품 위기",
    )
    shortage_qty = fields.Float(
        string="부족 수량",
        compute="_compute_shortage_risk",
        store=True,
        help="안전재고 대비 부족 수량 (음수면 결품 발생)",
    )

    company_id = fields.Many2one(
        "res.company", related="planning_run_id.company_id",
        store=True, index=True, readonly=True,
        help="계획 실행의 회사를 그대로 따른다. 활성 회사가 아니라 **계획의 회사**여야 "
             "다른 회사 계획의 산출물이 우리 목록에 섞이지 않는다. (PR08)",
    )

    @api.depends("stock_end", "safety_stock_qty")
    def _compute_shortage_risk(self):
        for rec in self:
            rec.shortage_qty = rec.stock_end - rec.safety_stock_qty
            rec.shortage_risk = rec.stock_end < rec.safety_stock_qty

    @api.depends("product_id", "plan_date")
    def _compute_display_name(self):
        for rec in self:
            pname = rec.product_id.display_name or ""
            dt = str(rec.plan_date) if rec.plan_date else ""
            rec.display_name = f"{pname} / {dt}"
