from odoo import api, fields, models


class OutsourcePlanningLine(models.Model):
    """외주 부품 조달 계획 라인"""
    _name = "outsource.planning.line"
    _description = "외주 조달 계획 라인"
    _order = "demand_date, product_id"

    planning_run_id = fields.Many2one(
        "outsource.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    product_id = fields.Many2one(
        "product.product", string="외주 부품",
        required=True, index=True,
        domain="[('is_outsourced', '=', True)]",
    )
    partner_id = fields.Many2one(
        "res.partner", string="협력사",
        domain="[('is_supplier_portal', '=', True)]",
    )

    # 수요 정보
    demand_date = fields.Date(string="필요일", required=True, index=True)
    demand_qty = fields.Float(string="소요량", help="완제품 BOM 전개 기준 소요량")

    # 발주 정보
    order_date = fields.Date(string="발주일", help="필요일 - 리드타임")
    order_qty = fields.Float(
        string="발주량",
        help="순소요량 (소요량 + 안전재고 - 현재고 - 입고예정)",
    )
    leadtime = fields.Integer(string="리드타임 (일)", default=3)

    # 재고 정보
    current_stock = fields.Float(string="현재고")
    incoming_qty = fields.Float(string="입고예정", help="발주 확정된 입고 예정 수량")
    safety_stock_qty = fields.Float(string="안전재고", help="향후 N일간 수요 합계")

    # 상태
    state = fields.Selection([
        ("draft", "계획"),
        ("ordered", "발주완료"),
        ("received", "입고완료"),
    ], string="상태", default="draft")

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    @api.depends("product_id", "demand_date")
    def _compute_display_name(self):
        for rec in self:
            pname = rec.product_id.display_name or ""
            dt = str(rec.demand_date) if rec.demand_date else ""
            rec.display_name = f"{pname} / {dt}"
