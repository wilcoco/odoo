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
    last_mold_id = fields.Many2one(
        "injection.mold", string="현재 장착 금형",
        help="전일 기준 이 사출기에 장착되어 있는 금형. "
             "스케줄링 시 금형 교환 여부 판단에 사용.",
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
