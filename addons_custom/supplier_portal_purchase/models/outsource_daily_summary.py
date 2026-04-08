from odoo import api, fields, models


class OutsourceDailySummary(models.Model):
    """외주 부품 일별 요약 (차트용)"""
    _name = "outsource.daily.summary"
    _description = "외주 부품 일별 요약"
    _order = "plan_date, product_id"
    _rec_name = "display_name"

    planning_run_id = fields.Many2one(
        "outsource.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    product_id = fields.Many2one(
        "product.product", string="외주 부품",
        required=True, index=True,
    )
    plan_date = fields.Date(string="날짜", required=True, index=True)

    # 수량
    demand_qty = fields.Float(string="소요량", help="해당일 소요량")
    incoming_qty = fields.Float(string="입고예정", help="해당일 입고 예정량")
    safety_stock_qty = fields.Float(string="안전재고", help="향후 N일간 수요 합계")

    # 재고
    stock_start = fields.Float(string="시작 재고", help="해당일 시작 시점 예상 재고")
    stock_end = fields.Float(string="종료 재고", help="시작 + 입고 - 소요")

    # 결품 위기
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
        help="안전재고 대비 부족 수량",
    )

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
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
