from odoo import api, fields, models, _


class IatfCompetenceMatrix(models.Model):
    _name = "iatf.competence.matrix"
    _description = "Competence Matrix Entry"
    _order = "employee_id, skill_name"
    _rec_name = "display_name"

    employee_id = fields.Many2one("hr.employee", string="Employee", required=True, index=True)
    department_id = fields.Many2one(
        "hr.department", string="Department",
        related="employee_id.department_id", store=True, readonly=True,
    )
    job_id = fields.Many2one(
        "hr.job", string="Job Position",
        related="employee_id.job_id", store=True, readonly=True,
    )

    skill_name = fields.Char(string="Skill / Competence", required=True)
    skill_category = fields.Selection(
        [
            ("process", "Process Knowledge"),
            ("quality", "Quality Tools"),
            ("safety", "Safety"),
            ("regulatory", "Regulatory / Compliance"),
            ("technical", "Technical Skill"),
            ("soft", "Soft Skill"),
        ],
        string="Category", default="process",
    )

    required_level = fields.Selection(
        [
            ("0", "Not Required"),
            ("1", "Awareness"),
            ("2", "Can perform under supervision"),
            ("3", "Can perform independently"),
            ("4", "Can train others"),
        ],
        string="Required Level", default="3",
    )
    current_level = fields.Selection(
        [
            ("0", "Not Trained"),
            ("1", "Awareness"),
            ("2", "Can perform under supervision"),
            ("3", "Can perform independently"),
            ("4", "Can train others"),
        ],
        string="Current Level", default="0",
    )
    gap = fields.Boolean(string="Gap Exists", compute="_compute_gap", store=True)

    last_training_date = fields.Date(string="Last Training Date")
    next_retraining_date = fields.Date(string="Next Retraining Date")
    certification = fields.Char(string="Certification / License")
    expiry_date = fields.Date(string="Certification Expiry")

    notes = fields.Text(string="Notes")

    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("required_level", "current_level")
    def _compute_gap(self):
        for rec in self:
            rec.gap = (int(rec.current_level or "0") < int(rec.required_level or "0"))

    @api.depends("employee_id", "skill_name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s" % (rec.employee_id.name or "", rec.skill_name or "")
