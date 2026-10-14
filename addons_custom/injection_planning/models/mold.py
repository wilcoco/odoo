from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


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
    changeover_hours_confirmed = fields.Boolean(
        string="교체시간 확인됨", readonly=True, copy=False,
        help="[R135 Q4] 담당자가 「교체시간 확인」 을 눌러 확인한 값. 저장(write)만으로는 확인으로 보지 않는다. "
             "확인 전 기존 값은 '기존 값·출처 미확인' 으로 보존한다(기본값이었다고 단정하지 않음). "
             "값을 바꾸면 확인이 풀린다.")
    changeover_confirmed_by = fields.Many2one("res.users", string="교체시간 확인자", readonly=True, copy=False)
    changeover_confirmed_at = fields.Datetime(string="교체시간 확인 일시", readonly=True, copy=False)
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
    # 사출기와 같은 이유. 실물 금형도 공유 자원이므로 확정 때 행을 바꿔 직렬화한다.
    x_planning_reservation_seq = fields.Integer(
        string="계획 예약 버전", default=0, copy=False, readonly=True,
        help="계획 확정이 이 금형을 잡을 때마다 오른다. 동시 확정을 직렬화하기 위한 값이다.",
    )
    responsible_id = fields.Many2one("res.users", string="담당자")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ("code_uniq", "unique(code)", "금형 코드는 고유해야 합니다."),
    ]

    @api.constrains("changeover_hours")
    def _check_changeover_hours(self):
        for rec in self:
            if rec.changeover_hours < 0:
                raise ValidationError(_("금형 교체시간은 음수일 수 없습니다: %s") % rec.display_name)

    def write(self, vals):
        if "changeover_hours" in vals and any(
                rec.changeover_hours != vals["changeover_hours"] for rec in self):
            # 값이 바뀌면 이전 확인은 더 이상 그 값에 대한 확인이 아니다.
            vals = dict(vals, changeover_hours_confirmed=False,
                        changeover_confirmed_by=False, changeover_confirmed_at=False)
        return super().write(vals)

    def action_confirm_changeover_hours(self):
        """명시적 확인 행위. 0 시간도 확인할 수 있다 — 그러면 '확인된 0시간' 이다."""
        self.check_access("write")
        return super(InjectionMold, self).write({
            "changeover_hours_confirmed": True, "changeover_confirmed_by": self.env.user.id,
            "changeover_confirmed_at": fields.Datetime.now()})

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}" if rec.code else rec.name
