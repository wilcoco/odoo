from odoo import api, fields, models, _


class InjectionMold(models.Model):
    _name = "injection.mold"
    _description = "사출 금형"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "code"
    _rec_name = "display_name"

    name = fields.Char(string="금형명", required=True, tracking=True)
    code = fields.Char(string="금형 코드", required=True, tracking=True, index=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)
    product_id = fields.Many2one(
        "product.product", string="생산 제품", tracking=True,
    )
    cavity_count = fields.Integer(string="캐비티 수", default=1, tracking=True)
    changeover_hours = fields.Float(
        string="금형 교체 시간 (시간)", default=2.0, tracking=True,
        help="금형 교체에 소요되는 시간 (시간 단위)",
    )
    required_clamping_ton = fields.Float(
        string="요구 형체력 (톤)", tracking=True,
        help="이 금형이 요구하는 최소 사출기 형체력(톤). 0이면 적합성 필터 미적용. "
             "배정 시 사출기 형체력(톤) ≥ 요구 형체력 인 조합만 선택된다.",
    )
    current_shots = fields.Integer(string="현재 샷카운트", default=0)
    guaranteed_shots = fields.Integer(
        string="보증 샷수", tracking=True,
        help="금형 보증 수명 (총 샷 수)",
    )
    state = fields.Selection(
        [
            ("active", "사용중"),
            ("maintenance", "정비중"),
            ("retired", "폐기"),
        ],
        string="상태",
        default="active",
        tracking=True,
    )
    responsible_id = fields.Many2one("res.users", string="담당자")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ("code_uniq", "unique(code)", "금형 코드는 고유해야 합니다."),
    ]

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name
