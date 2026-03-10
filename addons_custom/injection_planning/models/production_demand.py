from odoo import fields, models


class ProductionDemand(models.Model):
    _name = "injection.production.demand"
    _description = "생산 수요 데이터"
    _order = "demand_date, product_id"

    demand_date = fields.Date(string="수요 일자", required=True, index=True)
    product_id = fields.Many2one(
        "product.product", string="완성품", required=True, index=True,
    )
    quantity = fields.Float(string="수요 수량", required=True)
    demand_type = fields.Selection(
        [("daily", "일별"), ("hourly", "시간별")],
        string="유형",
        default="daily",
        required=True,
    )
    hour = fields.Integer(
        string="시간",
        help="시간대별 계획일 경우 (0~23)",
    )
    source = fields.Selection(
        [("oracle", "Oracle"), ("manual", "수동 입력")],
        string="데이터 소스",
        default="manual",
    )
    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행", ondelete="cascade", index=True,
    )
    state = fields.Selection(
        [("draft", "초안"), ("planned", "계획 반영"), ("done", "완료")],
        string="상태",
        default="draft",
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )
