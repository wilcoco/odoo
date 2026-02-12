from odoo import api, fields, models, _


class IatfRiskRegister(models.Model):
    _name = "iatf.risk.register"
    _description = "Risk & Opportunity Register (IATF 16949 §6.1)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "risk_score desc, id"

    name = fields.Char(
        string="Risk Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Title", required=True, tracking=True)
    entry_type = fields.Selection(
        [("risk", "Risk"), ("opportunity", "Opportunity")],
        string="Type", required=True, default="risk", tracking=True,
    )
    category = fields.Selection(
        [
            ("strategic", "Strategic"),
            ("operational", "Operational"),
            ("quality", "Quality / Product"),
            ("supply_chain", "Supply Chain"),
            ("regulatory", "Regulatory / Compliance"),
            ("financial", "Financial"),
            ("environmental", "Environmental"),
            ("safety", "Health & Safety"),
            ("it", "Information / Cyber Security"),
        ],
        string="Category", default="quality", tracking=True,
    )

    # ── Description ──
    description = fields.Html(string="Risk / Opportunity Description", required=True)
    source = fields.Char(string="Source / Trigger")
    affected_process = fields.Char(string="Affected Process(es)")
    interested_parties = fields.Char(string="Interested Parties")

    # ── Assessment ──
    likelihood = fields.Selection(
        [("1", "1 - Rare"), ("2", "2 - Unlikely"), ("3", "3 - Possible"),
         ("4", "4 - Likely"), ("5", "5 - Almost Certain")],
        string="Likelihood", default="3",
    )
    impact = fields.Selection(
        [("1", "1 - Negligible"), ("2", "2 - Minor"), ("3", "3 - Moderate"),
         ("4", "4 - Major"), ("5", "5 - Catastrophic")],
        string="Impact", default="3",
    )
    risk_score = fields.Integer(
        string="Risk Score", compute="_compute_risk_score", store=True,
        help="Likelihood × Impact",
    )
    risk_level = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        string="Risk Level", compute="_compute_risk_score", store=True,
    )

    # ── Treatment ──
    treatment_strategy = fields.Selection(
        [
            ("avoid", "Avoid"),
            ("mitigate", "Mitigate / Reduce"),
            ("transfer", "Transfer"),
            ("accept", "Accept"),
            ("exploit", "Exploit (Opportunity)"),
        ],
        string="Treatment Strategy", default="mitigate",
    )
    current_controls = fields.Html(string="Current Controls")
    planned_actions = fields.Html(string="Planned Actions / Treatment")
    responsible_id = fields.Many2one("res.users", string="Risk Owner",
                                      default=lambda self: self.env.user, tracking=True)
    due_date = fields.Date(string="Action Due Date")

    # ── Residual risk (after treatment) ──
    residual_likelihood = fields.Selection(
        [("1", "1 - Rare"), ("2", "2 - Unlikely"), ("3", "3 - Possible"),
         ("4", "4 - Likely"), ("5", "5 - Almost Certain")],
        string="Residual Likelihood", default="1",
    )
    residual_impact = fields.Selection(
        [("1", "1 - Negligible"), ("2", "2 - Minor"), ("3", "3 - Moderate"),
         ("4", "4 - Major"), ("5", "5 - Catastrophic")],
        string="Residual Impact", default="1",
    )
    residual_score = fields.Integer(
        string="Residual Score", compute="_compute_residual_score", store=True,
    )

    # ── Status ──
    state = fields.Selection(
        [
            ("identified", "Identified"),
            ("assessed", "Assessed"),
            ("treating", "Treatment In Progress"),
            ("monitored", "Monitored"),
            ("closed", "Closed"),
        ],
        string="Status", default="identified", tracking=True,
    )

    review_date = fields.Date(string="Next Review Date")
    notes = fields.Text(string="Notes")
    document_ids = fields.Many2many("iatf.document", string="Related Documents")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("likelihood", "impact")
    def _compute_risk_score(self):
        for rec in self:
            score = int(rec.likelihood or 0) * int(rec.impact or 0)
            rec.risk_score = score
            if score >= 20:
                rec.risk_level = "critical"
            elif score >= 12:
                rec.risk_level = "high"
            elif score >= 6:
                rec.risk_level = "medium"
            else:
                rec.risk_level = "low"

    @api.depends("residual_likelihood", "residual_impact")
    def _compute_residual_score(self):
        for rec in self:
            rec.residual_score = int(rec.residual_likelihood or 0) * int(rec.residual_impact or 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.risk.register") or _("New")
        return super().create(vals_list)

    def action_assess(self):
        self.write({"state": "assessed"})

    def action_treat(self):
        self.write({"state": "treating"})

    def action_monitor(self):
        self.write({"state": "monitored"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_reopen(self):
        self.write({"state": "assessed"})
