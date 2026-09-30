from odoo import api, fields, models


class MachineAvailability(models.Model):
    _name = "injection.machine.availability"
    _description = "사출기 가동 일정"
    _order = "date, workcenter_id"
    _rec_name = "display_name"

    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="사출기", required=True, index=True,
    )
    date = fields.Date(string="날짜", required=True, index=True)

    # 주간/야간 가용시간 (직접 입력)
    day_shift_hours = fields.Float(
        string="주간 가용시간 (h)", default=8.0,
        help="해당 날짜 주간 근무 가용시간. 0이면 주간 비가동.",
    )
    night_shift_hours = fields.Float(
        string="야간 가용시간 (h)", default=8.0,
        help="해당 날짜 야간 근무 가용시간. 0이면 야간 비가동.",
    )
    available_hours = fields.Float(
        string="총 가용시간 (h)", compute="_compute_available_hours", store=True,
    )
    # ── 이 필드의 정본이 무엇인지 ──
    # **현장이 기록하는 실제 장착 사실**이다. 계획 계산의 예측값이 아니다.
    # 예전에는 계획 계산이 끝나면서 이 값을 스스로 갱신했다. 그러면 계산해 본 것만으로
    # 실물 장착 이력이 바뀌고, 다른 초안 계산이나 재계산이 **다음 계획의 시작 금형**을
    # 임의로 바꾼다(독립검토 PR03). 지금은 계획이 이 값을 쓰지 않는다 — 읽기만 한다.
    # 계획이 예측한 종료 시점 금형은 그 계획의 마지막 라인(호기별)이 그대로 말해 준다.
    last_mold_id = fields.Many2one(
        "injection.mold", string="현재 장착 금형",
        help="이 날짜 기준으로 이 사출기에 실제 장착되어 있는 금형(현장 기록). "
             "계획은 교환 여부 판단에 이 값을 **읽기만** 하고 쓰지 않는다. "
             "계획이 예측한 장착 금형은 그 계획의 라인에서 확인한다.",
    )

    unavail_reason = fields.Selection(
        [
            ("breakdown", "고장"),
            ("maintenance", "정비"),
            ("no_order", "주문 없음"),
            ("holiday", "휴일"),
            ("other", "기타"),
        ],
        string="비가동 사유",
    )
    notes = fields.Text(string="비고")

    _sql_constraints = [
        (
            "unique_workcenter_date",
            "UNIQUE(workcenter_id, date)",
            "같은 사출기/날짜에 중복 일정을 등록할 수 없습니다.",
        ),
    ]

    @api.depends("day_shift_hours", "night_shift_hours")
    def _compute_available_hours(self):
        for rec in self:
            rec.available_hours = (rec.day_shift_hours or 0.0) + (rec.night_shift_hours or 0.0)

    @api.depends("workcenter_id", "date")
    def _compute_display_name(self):
        for rec in self:
            wc = rec.workcenter_id.name or ""
            dt = str(rec.date) if rec.date else ""
            rec.display_name = f"{wc} / {dt}"
