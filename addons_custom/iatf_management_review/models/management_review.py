from odoo import api, fields, models, _


class IatfManagementReview(models.Model):
    _name = "iatf.management.review"
    _description = "Management Review (IATF 16949 §9.3)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "meeting_date desc"

    name = fields.Char(
        string="Review Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Title", required=True, tracking=True)
    meeting_date = fields.Date(string="Meeting Date", required=True, default=fields.Date.today, tracking=True)
    review_period = fields.Char(string="Review Period", help="e.g. 2026-H1")

    chairperson_id = fields.Many2one("res.users", string="Chairperson", required=True,
                                      default=lambda self: self.env.user, tracking=True)
    attendee_ids = fields.Many2many("res.users", string="Attendees")

    # ── Inputs (§9.3.2) ──
    input_audit_results = fields.Html(string="Audit Results Summary")
    input_customer_feedback = fields.Html(string="Customer Feedback & Satisfaction")
    input_process_performance = fields.Html(string="Process Performance & Product Conformity")
    input_nc_corrective = fields.Html(string="Nonconformities & Corrective Actions")
    input_previous_actions = fields.Html(string="Status of Previous Review Actions")
    input_changes = fields.Html(string="Changes (Internal/External)")
    input_improvement_opportunities = fields.Html(string="Opportunities for Improvement")
    input_resource_needs = fields.Html(string="Resource Adequacy")

    # ── IATF Supplemental Inputs (§9.3.2.1) ──
    input_cost_poor_quality = fields.Html(string="Cost of Poor Quality (COPQ)")
    input_process_effectiveness = fields.Html(string="Process Effectiveness Measures")
    input_product_conformity = fields.Html(string="Product Conformity Measures")
    input_warranty = fields.Html(string="Warranty & Field Returns")
    input_customer_scorecards = fields.Html(string="Customer Scorecards")
    input_field_failures = fields.Html(string="Potential Field Failures (FMEA)")
    input_risk_assessment = fields.Html(string="Risk Assessment Summary")

    # ── Outputs (§9.3.3) ──
    output_improvement = fields.Html(string="Improvement Decisions")
    output_resource = fields.Html(string="Resource Needs / Changes")
    output_qms_changes = fields.Html(string="QMS Changes Required")
    output_quality_objectives = fields.Html(string="Quality Objectives Update")
    output_other = fields.Html(string="Other Decisions")

    # ── Action Items ──
    action_item_ids = fields.One2many("iatf.management.review.action", "review_id", string="Action Items")
    action_count = fields.Integer(compute="_compute_action_count")
    open_action_count = fields.Integer(compute="_compute_action_count")

    state = fields.Selection(
        [
            ("planned", "Planned"),
            ("in_progress", "In Progress"),
            ("minutes_issued", "Minutes Issued"),
            ("closed", "Closed"),
        ],
        string="Status", default="planned", tracking=True,
    )

    document_ids = fields.Many2many("iatf.document", string="Related Documents")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("action_item_ids", "action_item_ids.state")
    def _compute_action_count(self):
        for rec in self:
            rec.action_count = len(rec.action_item_ids)
            rec.open_action_count = len(rec.action_item_ids.filtered(lambda a: a.state != "done"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.management.review") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_issue_minutes(self):
        self.write({"state": "minutes_issued"})

    def action_close(self):
        self.write({"state": "closed"})
