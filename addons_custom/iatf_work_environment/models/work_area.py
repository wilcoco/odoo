from odoo import api, fields, models, _


class IatfWorkArea(models.Model):
    _name = "iatf.work.area"
    _description = "작업 구역 / 환경 기준 (IATF 16949 §7.1.4)"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(string="구역명", required=True, tracking=True)
    code = fields.Char(string="구역 코드")
    area_type = fields.Selection(
        [
            ("production", "생산 구역"),
            ("assembly", "조립 구역"),
            ("warehouse", "창고"),
            ("cleanroom", "클린룸"),
            ("lab", "시험실"),
            ("painting", "도장 구역"),
            ("welding", "용접 구역"),
            ("office", "사무실"),
            ("other", "기타"),
        ],
        string="구역 유형", default="production",
    )
    department_id = fields.Many2one("hr.department", string="관리 부서")
    responsible_id = fields.Many2one("res.users", string="담당자")

    # ── 환경 기준 ──
    temp_min = fields.Float(string="온도 하한 (°C)")
    temp_max = fields.Float(string="온도 상한 (°C)")
    humidity_min = fields.Float(string="습도 하한 (%)")
    humidity_max = fields.Float(string="습도 상한 (%)")
    cleanliness_class = fields.Char(string="청정도 등급", help="예: Class 10000, ISO 7")
    lighting_lux = fields.Float(string="조도 기준 (Lux)")
    noise_db = fields.Float(string="소음 기준 (dB)")
    dust_level = fields.Char(string="분진 기준")
    special_requirements = fields.Text(string="특수 요구사항")

    # ── 5S 기준 ──
    fiveS_check_cycle = fields.Selection(
        [("daily", "매일"), ("weekly", "주간"), ("monthly", "월간")],
        string="5S 점검 주기", default="weekly",
    )

    # ── 점검 기록 ──
    check_ids = fields.One2many("iatf.environment.check", "work_area_id", string="점검 기록")

    active = fields.Boolean(default=True)
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
