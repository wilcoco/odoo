from odoo import api, fields, models, _


class IatfContingencyPlan(models.Model):
    _name = "iatf.contingency.plan"
    _description = "Contingency Plan (IATF 16949 §6.1.2.3)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Plan Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Title", required=True, tracking=True)
    plan_type = fields.Selection(
        [
            ("supply", "Supply Chain Disruption"),
            ("equipment", "Key Equipment Failure"),
            ("labor", "Labor Shortage"),
            ("utility", "Utility Interruption (Power/Water/Gas)"),
            ("it", "IT System / Cyber Disruption"),
            ("natural", "Natural Disaster"),
            ("logistics", "Logistics / Transportation"),
            ("pandemic", "Pandemic / Health Emergency"),
            ("other", "Other"),
        ],
        string="Plan Type", required=True, default="equipment", tracking=True,
    )
    risk_description = fields.Html(string="Risk / Threat Description", required=True)

    # ── Impact ──
    affected_process = fields.Char(string="Affected Process(es)")
    affected_product_ids = fields.Many2many("product.product", string="Affected Products")
    impact_severity = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        string="Impact Severity", default="medium",
    )
    estimated_downtime = fields.Char(string="Estimated Downtime")

    # ── Prevention & Response ──
    prevention_measures = fields.Html(string="Prevention / Mitigation Measures")
    response_actions = fields.Html(string="Response Actions (if event occurs)")
    recovery_actions = fields.Html(string="Recovery Actions")
    communication_plan = fields.Html(string="Communication Plan (internal & customer)")
    alternate_source = fields.Char(string="Alternate Source / Backup")

    # ── Validation ──
    last_test_date = fields.Date(string="Last Test / Drill Date")
    test_frequency = fields.Char(string="Test Frequency", help="e.g. Annual, Semi-annual")
    test_result = fields.Html(string="Last Test Result / Lessons Learned")
    next_test_date = fields.Date(string="Next Test Due")

    # ── Ownership ──
    responsible_id = fields.Many2one("res.users", string="Plan Owner",
                                      default=lambda self: self.env.user, tracking=True)
    team_member_ids = fields.Many2many("res.users", string="Response Team")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("activated", "Activated (In Use)"),
            ("review", "Under Review"),
            ("obsolete", "Obsolete"),
        ],
        string="Status", default="draft", tracking=True,
    )

    document_ids = fields.Many2many("iatf.document", string="Related Documents")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.contingency.plan") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_trigger(self):
        self.write({"state": "activated"})

    def action_deactivate(self):
        self.write({"state": "active"})

    def action_review(self):
        self.write({"state": "review"})

    def action_obsolete(self):
        self.write({"state": "obsolete"})

    def action_reset_draft(self):
        self.write({"state": "draft"})
