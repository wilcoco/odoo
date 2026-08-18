from odoo import api, fields, models, _


class IatfMeasurementEquipment(models.Model):
    _name = "iatf.measurement.equipment"
    _description = "Measurement Equipment (IATF 16949 §7.1.5)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "equipment_id_number"

    name = fields.Char(string="장비명", required=True, tracking=True)
    equipment_id_number = fields.Char(string="장비 ID", required=True, tracking=True)
    equipment_type = fields.Selection(
        [
            ("caliper", "Caliper"),
            ("micrometer", "Micrometer"),
            ("gauge", "Gauge"),
            ("cmm", "CMM"),
            ("hardness", "Hardness Tester"),
            ("torque", "Torque Wrench"),
            ("scale", "Scale / Balance"),
            ("thermometer", "Thermometer"),
            ("pressure", "Pressure Gauge"),
            ("other", "Other"),
        ],
        string="유형", default="caliper", tracking=True,
    )
    manufacturer = fields.Char(string="제조사")
    model_number = fields.Char(string="모델")
    serial_number = fields.Char(string="시리얼")

    # ── Specification ──
    range_min = fields.Float(string="최소 범위", digits=(16, 4))
    range_max = fields.Float(string="최대 범위", digits=(16, 4))
    resolution = fields.Float(string="분해능", digits=(16, 6))
    accuracy = fields.Char(string="정확도")
    unit = fields.Char(string="단위")

    # ── Location / Ownership ──
    location = fields.Char(string="위치 / 작업장")
    custodian_id = fields.Many2one("res.users", string="관리자")
    department_id = fields.Many2one("hr.department", string="부서")

    # ── Calibration scheduling ──
    calibration_frequency_days = fields.Integer(string="교정 주기 (일)", default=365)
    last_calibration_date = fields.Date(string="최근 교정일")
    next_calibration_date = fields.Date(string="다음 교정 예정일", compute="_compute_next_cal", store=True)
    calibration_provider = fields.Char(string="교정 업체 / 시험소")
    is_overdue = fields.Boolean(compute="_compute_is_overdue", store=True)

    # ── Status ──
    state = fields.Selection(
        [
            ("active", "사용 중"),
            ("calibrating", "교정 중"),
            ("quarantine", "격리"),
            ("retired", "폐기"),
        ],
        string="상태", default="active", tracking=True,
    )

    calibration_record_ids = fields.One2many(
        "iatf.calibration.record", "equipment_id", string="교정 이력",
    )
    calibration_count = fields.Integer(compute="_compute_calibration_count")

    notes = fields.Text(string="비고")
    attachment_ids = fields.Many2many("ir.attachment", string="성적서 / 첨부파일")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("last_calibration_date", "calibration_frequency_days")
    def _compute_next_cal(self):
        from datetime import timedelta
        for rec in self:
            if rec.last_calibration_date and rec.calibration_frequency_days:
                rec.next_calibration_date = rec.last_calibration_date + timedelta(days=rec.calibration_frequency_days)
            else:
                rec.next_calibration_date = False

    @api.depends("next_calibration_date")
    def _compute_is_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = bool(rec.next_calibration_date and rec.next_calibration_date < today)

    @api.depends("calibration_record_ids")
    def _compute_calibration_count(self):
        for rec in self:
            rec.calibration_count = len(rec.calibration_record_ids)

    def action_send_to_calibration(self):
        self.write({"state": "calibrating"})

    def action_quarantine(self):
        self.write({"state": "quarantine"})

    def action_activate(self):
        self.write({"state": "active"})

    def action_retire(self):
        self.write({"state": "retired"})

    @api.model
    def _cron_calibration_overdue_alert(self):
        """매일 실행: 교정 기한 초과/임박 장비에 activity 알림"""
        from datetime import timedelta
        today = fields.Date.today()
        soon = today + timedelta(days=14)

        overdue = self.search([
            ("is_overdue", "=", True),
            ("state", "=", "active"),
        ])
        for eq in overdue:
            eq.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("교정 기한 초과: %s (예정일: %s)") % (eq.name, eq.next_calibration_date),
                user_id=eq.custodian_id.id or self.env.ref("base.user_admin").id,
                date_deadline=today,
            )

        upcoming = self.search([
            ("next_calibration_date", "<=", soon),
            ("next_calibration_date", ">=", today),
            ("state", "=", "active"),
        ])
        for eq in upcoming:
            existing = self.env["mail.activity"].search([
                ("res_model", "=", "iatf.measurement.equipment"),
                ("res_id", "=", eq.id),
                ("summary", "like", "교정 기한 임박"),
            ], limit=1)
            if not existing:
                eq.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("교정 기한 임박: %s (예정일: %s)") % (eq.name, eq.next_calibration_date),
                    user_id=eq.custodian_id.id or self.env.ref("base.user_admin").id,
                    date_deadline=eq.next_calibration_date,
                )
