from odoo import api, fields, models, _


class IatfCalibrationRecord(models.Model):
    _name = "iatf.calibration.record"
    _description = "Calibration Record"
    _inherit = ["mail.thread"]
    _order = "calibration_date desc"

    name = fields.Char(
        string="Calibration #", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    equipment_id = fields.Many2one(
        "iatf.measurement.equipment", string="Equipment", required=True,
        ondelete="cascade", index=True,
    )
    calibration_date = fields.Date(string="Calibration Date", required=True, default=fields.Date.today)
    calibration_type = fields.Selection(
        [
            ("internal", "Internal"),
            ("external", "External (Lab)"),
        ],
        string="Calibration Type", default="external",
    )
    provider = fields.Char(string="Provider / Lab")
    certificate_number = fields.Char(string="Certificate #")

    # ── Results ──
    result = fields.Selection(
        [
            ("pass", "Pass — Within Tolerance"),
            ("adjusted", "Adjusted & Pass"),
            ("fail", "Fail — Out of Tolerance"),
            ("limited", "Limited Use"),
        ],
        string="Result", required=True, default="pass", tracking=True,
    )
    measured_values = fields.Text(string="Measured Values / Data")
    uncertainty = fields.Char(string="Measurement Uncertainty")

    # ── Environmental conditions ──
    temperature = fields.Float(string="Temperature (°C)")
    humidity = fields.Float(string="Humidity (%)")

    performed_by = fields.Many2one("res.users", string="Performed By", default=lambda self: self.env.user)
    next_due_date = fields.Date(string="Next Due Date")

    notes = fields.Text(string="Notes")
    attachment_ids = fields.Many2many("ir.attachment", string="Certificate Files")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.calibration.record") or _("New")
        records = super().create(vals_list)
        for rec in records:
            rec.equipment_id.write({
                "last_calibration_date": rec.calibration_date,
                "state": "active" if rec.result in ("pass", "adjusted") else "quarantine",
            })
        return records
