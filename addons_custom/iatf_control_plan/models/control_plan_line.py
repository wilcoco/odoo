from odoo import fields, models


class IatfControlPlanLine(models.Model):
    _name = "iatf.control.plan.line"
    _description = "Control Plan Line Item"
    _order = "sequence, id"

    control_plan_id = fields.Many2one(
        "iatf.control.plan", string="Control Plan", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)

    # ── Process ──
    process_step_number = fields.Char(string="Step #")
    process_name = fields.Char(string="Process Name / Operation")
    machine_device = fields.Char(string="Machine / Device / Tool")

    # ── Characteristic ──
    characteristic_number = fields.Char(string="Char. #")
    characteristic_name = fields.Char(string="Characteristic", required=True)
    characteristic_type = fields.Selection(
        [
            ("product", "Product"),
            ("process", "Process"),
        ],
        string="Char. Type", default="product",
    )
    special_characteristic = fields.Selection(
        [
            ("none", "None"),
            ("cc", "CC - Critical"),
            ("sc", "SC - Significant"),
            ("hi", "HI - High Impact"),
        ],
        string="Special Char.", default="none",
    )

    # ── Specification ──
    specification = fields.Char(string="Product/Process Specification / Tolerance")
    evaluation_method = fields.Char(string="Evaluation / Measurement Technique")
    sample_size = fields.Char(string="Sample Size")
    sample_frequency = fields.Char(string="Sample Frequency")

    # ── Control Method ──
    control_method = fields.Text(string="Control Method")
    reaction_plan = fields.Text(string="Reaction Plan")

    # ── FMEA link ──
    fmea_line_id = fields.Many2one("iatf.fmea.line", string="FMEA Line Reference")

    notes = fields.Text(string="Notes")
