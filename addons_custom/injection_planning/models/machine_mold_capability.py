from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class MachineMoldCapability(models.Model):
    _name = "injection.machine.mold.capability"
    _description = "사출기-금형 조합 능력"
    _order = "workcenter_id, mold_id"

    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="사출기", required=True, index=True,
    )
    mold_id = fields.Many2one(
        "injection.mold", string="금형", required=True, index=True,
    )
    product_id = fields.Many2one(
        related="mold_id.product_id", string="생산 제품", store=True, readonly=True,
    )
    cavity_count = fields.Integer(
        related="mold_id.cavity_count", string="캐비티 수", readonly=True,
    )
    required_clamping_ton = fields.Float(
        related="mold_id.required_clamping_ton", string="요구 형체력(톤)", readonly=True,
    )
    machine_clamping_ton = fields.Float(
        related="workcenter_id.x_clamping_force_ton", string="사출기 형체력(톤)", readonly=True,
    )

    # ── 변수 ──
    cycle_time = fields.Float(
        string="사이클타임 (초)", required=True, default=45.0,
        help="1회 사출 사이클 소요 시간 (초)",
    )
    defect_rate = fields.Float(
        string="불량율 (%)", default=2.0,
        help="이 사출기-금형 조합의 불량율",
    )
    initial_scrap = fields.Integer(
        string="초기 불량 수 (개)", default=20,
        help="금형 교체 후 초기 불량 수량",
    )

    # ── 계산 ──
    hourly_capacity = fields.Float(
        string="시간당 생산능력",
        compute="_compute_hourly_capacity",
        store=True,
    )

    changeover_override = fields.Boolean(
        string="이 조합 교체시간 사용",
        help="[R135 검토 #3] 켜면 아래 값을 쓴다 — **0 도 확인된 0시간으로 보존**한다. 끄면 금형 값을 쓴다. "
             "0/미입력을 곧바로 금형 fallback 으로 읽지 않기 위한 별도 표지다.")
    changeover_hours = fields.Float(
        string="이 조합 교체시간 (h)",
        help="[R135] 이 사출기에서 이 금형을 교체할 때 걸리는 시간. 「이 조합 교체시간 사용」 이 켜져 있을 때만 적용.")
    active = fields.Boolean(default=True)

    @api.constrains("changeover_hours")
    def _check_changeover_hours(self):
        for rec in self:
            if rec.changeover_hours < 0:
                raise ValidationError(_("조합 교체시간은 음수일 수 없습니다."))

    _sql_constraints = [
        (
            "workcenter_mold_uniq",
            "unique(workcenter_id, mold_id)",
            "사출기-금형 조합은 중복될 수 없습니다.",
        ),
    ]

    @api.depends("cycle_time", "cavity_count")
    def _compute_hourly_capacity(self):
        for rec in self:
            if rec.cycle_time > 0:
                rec.hourly_capacity = (3600.0 / rec.cycle_time) * (rec.cavity_count or 1)
            else:
                rec.hourly_capacity = 0.0
