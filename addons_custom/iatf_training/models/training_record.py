from odoo import api, fields, models, _


class IatfTrainingRecord(models.Model):
    _name = "iatf.training.record"
    _description = "Training Record (IATF 16949 §7.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "training_date desc"

    name = fields.Char(
        string="Training Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Training Title", required=True, tracking=True)
    training_type = fields.Selection(
        [
            ("classroom", "Classroom"),
            ("ojt", "On-the-Job Training (OJT)"),
            ("external", "External Training"),
            ("elearning", "E-Learning"),
            ("certification", "Certification / Re-certification"),
        ],
        string="Type", required=True, default="classroom", tracking=True,
    )

    training_date = fields.Date(string="Training Date", required=True, default=fields.Date.today)
    duration_hours = fields.Float(string="Duration (hours)")
    trainer_id = fields.Many2one("res.users", string="Trainer / Instructor")
    trainer_external = fields.Char(string="External Trainer Name")

    # ── Participants ──
    employee_ids = fields.Many2many("hr.employee", string="Participants")
    participant_count = fields.Integer(compute="_compute_participant_count")
    department_id = fields.Many2one("hr.department", string="Department")

    # ── Content ──
    topics = fields.Html(string="Training Topics / Content")
    iatf_clause = fields.Char(string="Related IATF Clause", help="e.g. §7.2, §8.5.1")
    process_name = fields.Char(string="Related Process")

    # ── Evaluation ──
    evaluation_method = fields.Selection(
        [
            ("test", "Written Test"),
            ("practical", "Practical Demonstration"),
            ("observation", "Supervisor Observation"),
            ("quiz", "Quiz"),
            ("none", "No Evaluation"),
        ],
        string="Evaluation Method", default="none",
    )
    pass_criteria = fields.Char(string="Pass Criteria", help="e.g. ≥ 80% score")
    effectiveness_verified = fields.Boolean(string="Effectiveness Verified", tracking=True)
    effectiveness_notes = fields.Text(string="Effectiveness Notes")

    # ── Status ──
    state = fields.Selection(
        [
            ("planned", "Planned"),
            ("completed", "Completed"),
            ("verified", "Effectiveness Verified"),
            ("cancelled", "Cancelled"),
        ],
        string="Status", default="planned", tracking=True,
    )

    document_ids = fields.Many2many("iatf.document", string="Related Documents")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("employee_ids")
    def _compute_participant_count(self):
        for rec in self:
            rec.participant_count = len(rec.employee_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.training.record") or _("New")
        return super().create(vals_list)

    def action_complete(self):
        self.write({"state": "completed"})

    def action_verify_effectiveness(self):
        self.write({"state": "verified", "effectiveness_verified": True})

    def action_cancel(self):
        self.write({"state": "cancelled"})
