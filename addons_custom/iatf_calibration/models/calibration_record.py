from odoo import api, fields, models, _


class IatfCalibrationRecord(models.Model):
    _name = "iatf.calibration.record"
    _description = "Calibration Record"
    _inherit = ["mail.thread"]
    _order = "calibration_date desc"

    name = fields.Char(
        string="교정 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    equipment_id = fields.Many2one(
        "iatf.measurement.equipment", string="장비", required=True,
        ondelete="cascade", index=True,
    )
    calibration_date = fields.Date(string="교정일", required=True, default=fields.Date.today)
    calibration_type = fields.Selection(
        [
            ("internal", "내부"),
            ("external", "외부 (시험소)"),
        ],
        string="교정 유형", default="external",
    )
    provider = fields.Char(string="교정 업체")
    certificate_number = fields.Char(string="성적서 번호")

    # ── Results ──
    result = fields.Selection(
        [
            ("pass", "합격"),
            ("adjusted", "조정 후 합격"),
            ("fail", "불합격"),
            ("limited", "제한 사용"),
        ],
        string="결과", required=True, default="pass", tracking=True,
    )
    measured_values = fields.Text(string="측정값 / 데이터")
    uncertainty = fields.Char(string="측정 불확도")

    # ── Environmental conditions ──
    temperature = fields.Float(string="온도 (\xc2\xb0C)")
    humidity = fields.Float(string="습도 (%)")

    performed_by = fields.Many2one("res.users", string="수행자", default=lambda self: self.env.user)
    next_due_date = fields.Date(string="다음 교정 예정일")

    notes = fields.Text(string="비고")
    attachment_ids = fields.Many2many("ir.attachment", string="성적서 파일")
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
