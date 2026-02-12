from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfAudit(models.Model):
    _name = "iatf.audit"
    _description = "Internal Audit (IATF 16949 §9.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "planned_date desc"

    name = fields.Char(
        string="Audit Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Audit Title", required=True, tracking=True)
    audit_type = fields.Selection(
        [
            ("system", "QMS / System Audit"),
            ("process", "Process Audit (VDA 6.3)"),
            ("product", "Product Audit"),
            ("supplier", "Supplier Audit"),
        ],
        string="Audit Type", required=True, default="system", tracking=True,
    )

    # ── Planning ──
    planned_date = fields.Date(string="Planned Date", required=True, tracking=True)
    actual_date = fields.Date(string="Actual Date")
    department_id = fields.Many2one("hr.department", string="Audited Area / Department")
    process_name = fields.Char(string="Audited Process")
    standard_reference = fields.Char(
        string="Standard / Clause Reference",
        help="e.g. IATF 16949 §8.5, VDA 6.3 P5-P7",
    )

    # ── Auditors ──
    lead_auditor_id = fields.Many2one("res.users", string="Lead Auditor", required=True, tracking=True)
    auditor_ids = fields.Many2many("res.users", string="Audit Team")

    # ── Findings ──
    finding_ids = fields.One2many("iatf.audit.finding", "audit_id", string="Findings")
    finding_count = fields.Integer(compute="_compute_finding_count")
    nc_major_count = fields.Integer(string="Major NCs", compute="_compute_finding_count", store=True)
    nc_minor_count = fields.Integer(string="Minor NCs", compute="_compute_finding_count", store=True)
    observation_count = fields.Integer(string="Observations", compute="_compute_finding_count", store=True)

    # ── Score (for VDA 6.3) ──
    vda_score = fields.Float(string="VDA 6.3 Score (%)", digits=(5, 1))
    vda_grade = fields.Selection(
        [
            ("a", "A (≥ 90%)"),
            ("b", "B (80–89%)"),
            ("c", "C (< 80%)"),
        ],
        string="VDA Grade",
    )

    # ── Status ──
    state = fields.Selection(
        [
            ("planned", "Planned"),
            ("in_progress", "In Progress"),
            ("report", "Report Issued"),
            ("follow_up", "Follow-up"),
            ("closed", "Closed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status", default="planned", tracking=True,
    )
    audit_report = fields.Html(string="Audit Report / Summary")
    document_ids = fields.Many2many("iatf.document", string="Related Documents")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("finding_ids", "finding_ids.finding_type")
    def _compute_finding_count(self):
        for audit in self:
            findings = audit.finding_ids
            audit.finding_count = len(findings)
            audit.nc_major_count = len(findings.filtered(lambda f: f.finding_type == "major"))
            audit.nc_minor_count = len(findings.filtered(lambda f: f.finding_type == "minor"))
            audit.observation_count = len(findings.filtered(lambda f: f.finding_type == "observation"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.audit") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "in_progress", "actual_date": fields.Date.today()})

    def action_issue_report(self):
        self.write({"state": "report"})

    def action_follow_up(self):
        self.write({"state": "follow_up"})

    def action_close(self):
        for audit in self:
            open_findings = audit.finding_ids.filtered(lambda f: f.state != "closed")
            if open_findings:
                raise UserError(_("%d finding(s) still open.") % len(open_findings))
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})
