from odoo import api, fields, models, _


class IatfFmeaLine(models.Model):
    _name = "iatf.fmea.line"
    _description = "FMEA Line Item (Failure Mode)"
    _order = "rpn desc, id"

    fmea_id = fields.Many2one(
        "iatf.fmea", string="FMEA", required=True, ondelete="cascade", index=True,
    )
    fmea_type = fields.Selection(related="fmea_id.fmea_type", store=True, readonly=True)

    # ── Step 1: Structure Analysis ──
    process_step = fields.Char(string="Process Step / Function")
    process_function = fields.Text(string="Requirements / Function")

    # ── Step 2: Function Analysis ──
    failure_mode = fields.Char(string="Failure Mode", required=True)
    failure_effect = fields.Text(string="Failure Effect(s)")
    failure_cause = fields.Text(string="Failure Cause(s)")

    # ── Step 3: Failure Analysis (S/O/D ratings) ──
    severity = fields.Integer(
        string="Severity (S)", default=1,
        help="1 = No effect, 10 = Hazardous without warning",
    )
    occurrence = fields.Integer(
        string="Occurrence (O)", default=1,
        help="1 = Remote, 10 = Very high / Almost certain",
    )
    detection = fields.Integer(
        string="Detection (D)", default=1,
        help="1 = Almost certain detection, 10 = No detection",
    )
    rpn = fields.Integer(
        string="RPN", compute="_compute_rpn", store=True,
        help="Risk Priority Number = S × O × D",
    )

    # ── AIAG-VDA Action Priority (AP) ──
    action_priority = fields.Selection(
        [
            ("high", "High"),
            ("medium", "Medium"),
            ("low", "Low"),
        ],
        string="Action Priority (AP)", compute="_compute_action_priority", store=True,
    )

    # ── Step 4: Current Controls ──
    current_prevention = fields.Text(string="Current Prevention Controls")
    current_detection = fields.Text(string="Current Detection Controls")

    # ── Step 5: Recommended Actions ──
    recommended_action = fields.Text(string="Recommended Action")
    action_responsible_id = fields.Many2one("res.users", string="Action Responsible")
    action_due_date = fields.Date(string="Action Due Date")
    action_status = fields.Selection(
        [
            ("open", "Open"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
            ("verified", "Verified"),
        ],
        string="Action Status", default="open",
    )
    action_taken = fields.Text(string="Action Taken")
    action_completion_date = fields.Date(string="Completion Date")

    # ── Step 6: Re-evaluation after action ──
    severity_after = fields.Integer(string="S (after)", default=0)
    occurrence_after = fields.Integer(string="O (after)", default=0)
    detection_after = fields.Integer(string="D (after)", default=0)
    rpn_after = fields.Integer(
        string="RPN (after)", compute="_compute_rpn_after", store=True,
    )

    # ── Special characteristics ──
    special_characteristic = fields.Selection(
        [
            ("none", "None"),
            ("cc", "CC - Critical Characteristic"),
            ("sc", "SC - Significant Characteristic"),
            ("hi", "HI - High Impact"),
        ],
        string="Special Char.", default="none",
    )

    notes = fields.Text(string="Notes")

    @api.depends("severity", "occurrence", "detection")
    def _compute_rpn(self):
        for line in self:
            line.rpn = line.severity * line.occurrence * line.detection

    @api.depends("severity_after", "occurrence_after", "detection_after")
    def _compute_rpn_after(self):
        for line in self:
            line.rpn_after = line.severity_after * line.occurrence_after * line.detection_after

    @api.depends("severity", "occurrence", "detection")
    def _compute_action_priority(self):
        for line in self:
            s, o, d = line.severity, line.occurrence, line.detection
            if s >= 9 or (s >= 7 and o >= 4) or (line.rpn >= 200):
                line.action_priority = "high"
            elif (s >= 5 and o >= 4) or (line.rpn >= 100):
                line.action_priority = "medium"
            else:
                line.action_priority = "low"
