from odoo import api, fields, models, _


class IatfMeasurementEquipment(models.Model):
    _name = "iatf.measurement.equipment"
    _description = "Measurement Equipment (IATF 16949 §7.1.5)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "equipment_id_number"

    name = fields.Char(string="Equipment Name", required=True, tracking=True)
    equipment_id_number = fields.Char(string="Equipment ID #", required=True, tracking=True)
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
        string="Type", default="caliper", tracking=True,
    )
    manufacturer = fields.Char(string="Manufacturer / Brand")
    model_number = fields.Char(string="Model #")
    serial_number = fields.Char(string="Serial #")

    # ── Specification ──
    range_min = fields.Float(string="Range Min", digits=(16, 4))
    range_max = fields.Float(string="Range Max", digits=(16, 4))
    resolution = fields.Float(string="Resolution", digits=(16, 6))
    accuracy = fields.Char(string="Accuracy")
    unit = fields.Char(string="Unit")

    # ── Location / Ownership ──
    location = fields.Char(string="Location / Work Center")
    custodian_id = fields.Many2one("res.users", string="Custodian")
    department_id = fields.Many2one("hr.department", string="Department")

    # ── Calibration scheduling ──
    calibration_frequency_days = fields.Integer(string="Calibration Frequency (days)", default=365)
    last_calibration_date = fields.Date(string="Last Calibration Date")
    next_calibration_date = fields.Date(string="Next Calibration Due", compute="_compute_next_cal", store=True)
    calibration_provider = fields.Char(string="Calibration Provider / Lab")
    is_overdue = fields.Boolean(compute="_compute_is_overdue", store=True)

    # ── Status ──
    state = fields.Selection(
        [
            ("active", "Active / In Use"),
            ("calibrating", "Out for Calibration"),
            ("quarantine", "Quarantined"),
            ("retired", "Retired"),
        ],
        string="Status", default="active", tracking=True,
    )

    calibration_record_ids = fields.One2many(
        "iatf.calibration.record", "equipment_id", string="Calibration History",
    )
    calibration_count = fields.Integer(compute="_compute_calibration_count")

    notes = fields.Text(string="Notes")
    attachment_ids = fields.Many2many("ir.attachment", string="Certificates / Attachments")
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
