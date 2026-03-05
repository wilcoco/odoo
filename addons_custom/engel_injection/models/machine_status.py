from odoo import fields, models


class EngelMachineStatus(models.Model):
    _name = "engel.machine.status"
    _description = "사출기 실시간 상태"
    _order = "updated_at desc"
    _rec_name = "machine_name"

    machine_name = fields.Char(string="설비명", required=True, index=True)
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장")
    status = fields.Selection(
        [
            ("running", "가동 중"),
            ("stopped", "정지"),
            ("alarm", "알람"),
            ("idle", "대기"),
        ],
        string="상태",
        default="idle",
    )
    current_mo_id = fields.Many2one("mrp.production", string="현재 MO")
    last_shot_time = fields.Datetime(string="최근 샷 시각")
    total_shots_today = fields.Integer(string="금일 생산 수")
    cycle_time_avg = fields.Float(string="평균 사이클 타임 (초)", digits=(16, 2))
    updated_at = fields.Datetime(
        string="업데이트 시각", default=fields.Datetime.now,
    )

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ("machine_name_uniq", "unique(machine_name)", "설비명은 고유해야 합니다."),
    ]
