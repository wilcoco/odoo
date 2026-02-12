from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfNonconformity(models.Model):
    _name = "iatf.nonconformity"
    _description = "Nonconformity Report (IATF 16949 §10.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    # ── Identification ──
    name = fields.Char(
        string="NC Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Title", required=True, tracking=True)

    nc_type = fields.Selection(
        [
            ("internal", "Internal NC"),
            ("supplier", "Supplier NC"),
            ("customer", "Customer Complaint"),
            ("audit", "Audit Finding"),
            ("process", "Process NC"),
        ],
        string="NC Type", required=True, default="internal", tracking=True,
    )
    severity = fields.Selection(
        [
            ("minor", "Minor"),
            ("major", "Major"),
            ("critical", "Critical"),
        ],
        string="Severity", required=True, default="minor", tracking=True,
    )
    priority = fields.Selection(
        [
            ("0", "Normal"),
            ("1", "High"),
            ("2", "Urgent"),
        ],
        string="Priority", default="0",
    )

    # ── 8D Discipline mapping ──
    # D1: Team
    team_leader_id = fields.Many2one("res.users", string="Team Leader (D1)", tracking=True)
    team_member_ids = fields.Many2many("res.users", string="Team Members (D1)")

    # D2: Problem Description
    problem_description = fields.Html(string="Problem Description (D2)", tracking=True)
    detection_date = fields.Date(string="Detection Date", default=fields.Date.today, required=True)
    detection_location = fields.Char(string="Detection Location")
    detected_by = fields.Many2one("res.users", string="Detected By", default=lambda self: self.env.user)

    # D3: Interim Containment Action
    containment_action = fields.Html(string="Containment Action (D3)")
    containment_date = fields.Date(string="Containment Date")
    containment_responsible_id = fields.Many2one("res.users", string="Containment Responsible")
    containment_verified = fields.Boolean(string="Containment Verified")

    # D4: Root Cause Analysis
    root_cause_method = fields.Selection(
        [
            ("5why", "5-Why Analysis"),
            ("fishbone", "Fishbone / Ishikawa"),
            ("fta", "Fault Tree Analysis"),
            ("other", "Other"),
        ],
        string="Root Cause Method (D4)",
    )
    root_cause = fields.Html(string="Root Cause (D4)")

    # D5 & D6: handled via corrective_action_ids
    # D7: Preventive Action
    preventive_action = fields.Html(string="Preventive / Systemic Action (D7)")

    # D6: Verification
    verification_result = fields.Html(string="Verification of Effectiveness (D6)")

    # D7: Preventive — already defined below

    # D8: Closure
    closure_notes = fields.Html(string="Team Recognition / Closure Notes (D8)")

    # ── Timeline ──
    target_close_date = fields.Date(string="Target Close Date", tracking=True)
    actual_close_date = fields.Date(string="Actual Close Date")

    # ── Responsible ──
    responsible_id = fields.Many2one("res.users", string="Responsible",
                                      default=lambda self: self.env.user, tracking=True)

    notes = fields.Text(string="Notes")

    # ── References ──
    product_id = fields.Many2one("product.product", string="Product")
    production_id = fields.Many2one("mrp.production", string="Manufacturing Order")
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial")
    partner_id = fields.Many2one(
        "res.partner", string="Related Partner",
        help="Customer (complaint) or Supplier (supplier NC)",
    )
    quantity_affected = fields.Float(string="Quantity Affected")
    quantity_rejected = fields.Float(string="Quantity Rejected")

    # ── Disposition ──
    disposition = fields.Selection(
        [
            ("use_as_is", "Use As-Is"),
            ("rework", "Rework"),
            ("scrap", "Scrap"),
            ("return", "Return to Supplier"),
            ("sort", "Sort / Inspect 100%"),
            ("concession", "Customer Concession"),
        ],
        string="Disposition", tracking=True,
    )

    # ── Relations ──
    corrective_action_ids = fields.One2many(
        "iatf.corrective.action", "nonconformity_id", string="Corrective Actions (D5/D6)",
    )
    corrective_action_count = fields.Integer(compute="_compute_ca_count")
    document_ids = fields.Many2many("iatf.document", string="Related Documents")
    attachment_ids = fields.Many2many("ir.attachment", string="Evidence / Attachments")

    # ── Workflow ──
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("containment", "D3 Containment"),
            ("analysis", "D4 Root Cause"),
            ("corrective", "D5/D6 Corrective Action"),
            ("verification", "D7 Verification"),
            ("closed", "D8 Closed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status", default="draft", required=True, tracking=True,
    )

    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company,
    )

    # ── Cost tracking ──
    cost_internal = fields.Float(string="Internal Cost")
    cost_external = fields.Float(string="External Cost")
    cost_total = fields.Float(string="Total Cost", compute="_compute_cost_total", store=True)

    @api.depends("cost_internal", "cost_external")
    def _compute_cost_total(self):
        for rec in self:
            rec.cost_total = rec.cost_internal + rec.cost_external

    @api.depends("corrective_action_ids")
    def _compute_ca_count(self):
        for rec in self:
            rec.corrective_action_count = len(rec.corrective_action_ids)

    # ── CRUD ──

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.nonconformity") or _("New")
        return super().create(vals_list)

    # ── Workflow actions ──

    def action_start_containment(self):
        self.write({"state": "containment"})

    def action_start_analysis(self):
        for rec in self:
            if not rec.containment_action:
                raise UserError(_("Please document the containment action (D3) before proceeding."))
        self.write({"state": "analysis"})

    def action_start_corrective(self):
        for rec in self:
            if not rec.root_cause:
                raise UserError(_("Please document the root cause (D4) before proceeding."))
        self.write({"state": "corrective"})

    def action_start_verification(self):
        for rec in self:
            if not rec.corrective_action_ids:
                raise UserError(_("Please add at least one corrective action (D5/D6)."))
        self.write({"state": "verification"})

    def action_close(self):
        for rec in self:
            open_cas = rec.corrective_action_ids.filtered(lambda ca: ca.state != "verified")
            if open_cas:
                raise UserError(
                    _("All corrective actions must be verified before closing. "
                      "%d action(s) still open.") % len(open_cas)
                )
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_view_corrective_actions(self):
        self.ensure_one()
        return {
            "name": _("Corrective Actions"),
            "type": "ir.actions.act_window",
            "res_model": "iatf.corrective.action",
            "view_mode": "list,form",
            "domain": [("nonconformity_id", "=", self.id)],
            "context": {"default_nonconformity_id": self.id},
        }
