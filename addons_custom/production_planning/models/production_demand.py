from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ProductionDemand(models.Model):
    """전체 완제품 생산 수요 (사출/외주/조립 공통)"""
    _name = "production.demand"
    _description = "생산 수요 데이터"
    _order = "demand_date, product_id"

    name = fields.Char(
        string="참조",
        compute="_compute_name",
        store=True,
    )
    demand_date = fields.Date(
        string="수요일",
        required=True,
        index=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="완제품",
        required=True,
        index=True,
    )
    quantity = fields.Float(
        string="수요량",
        required=True,
    )
    demand_type = fields.Selection(
        [
            ("daily", "일별"),
            ("hourly", "시간별"),
        ],
        string="유형",
        default="daily",
        required=True,
    )
    hour = fields.Integer(
        string="시간",
        help="시간대별 계획일 경우 (0~23)",
    )
    source = fields.Selection(
        [
            ("oracle", "Oracle"),
            ("manual", "수동 입력"),
            ("forecast", "예측"),
            ("order", "수주"),
            ("test", "테스트"),
        ],
        string="데이터 소스",
        default="manual",
    )
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("confirmed", "확정"),
            ("done", "완료"),
            ("cancelled", "취소"),
        ],
        string="상태",
        default="draft",
        index=True,
    )
    notes = fields.Text(string="비고")
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
    )

    @api.depends("product_id", "demand_date")
    def _compute_name(self):
        for rec in self:
            product = rec.product_id.default_code or rec.product_id.name or ""
            date_str = str(rec.demand_date) if rec.demand_date else ""
            rec.name = f"{product} / {date_str}"

    def action_confirm(self):
        """수요 확정 — 수량이 0 이하인 수요는 확정하지 않는다(R144 정책 ①, 2026-09-15)."""
        bad = self.filtered(lambda r: r.state == "draft" and r.quantity <= 0)
        if bad:
            raise UserError(_("수량이 0 이하인 수요는 확정할 수 없습니다: %s") % ", ".join(bad.mapped("display_name")))
        self.filtered(lambda r: r.state == "draft").write({"state": "confirmed"})

    def write(self, vals):
        """확정·완료된 수요의 수량·일자·제품은 잠근다 — 바꾸려면 '초안으로' 되돌린 뒤 수정(R144 정책 ①)."""
        locked = {"quantity", "demand_date", "product_id"} & set(vals)
        if locked and not self.env.context.get("demand_unlock"):
            frozen = self.filtered(lambda r: r.state in ("confirmed", "done"))
            if frozen:
                raise UserError(_("확정/완료된 수요는 수량·일자·제품을 바꿀 수 없습니다. '초안으로' 되돌린 뒤 수정하십시오: %s")
                                % ", ".join(frozen.mapped("display_name")))
        return super().write(vals)

    def action_done(self):
        """완료 처리"""
        self.filtered(lambda r: r.state == "confirmed").write({"state": "done"})

    def action_cancel(self):
        """취소"""
        self.filtered(lambda r: r.state != "done").write({"state": "cancelled"})

    def action_reset_draft(self):
        """초안으로 — 취소·확정 수요를 되돌린다(확정 수요의 수정 경로, R144 정책 ①). 완료는 되돌리지 않는다."""
        self.filtered(lambda r: r.state in ("cancelled", "confirmed")).write({"state": "draft"})
