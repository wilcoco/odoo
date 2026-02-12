from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfPpapSubmission(models.Model):
    _name = "iatf.ppap.submission"
    _description = "PPAP Submission (IATF 16949 §8.3.4.4)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="PPAP Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Title", required=True, tracking=True)
    product_id = fields.Many2one("product.product", string="Product", tracking=True)
    part_number = fields.Char(string="Part Number")
    customer_id = fields.Many2one("res.partner", string="Customer", required=True, tracking=True)

    submission_level = fields.Selection(
        [
            ("1", "Level 1 — Warrant + limited data"),
            ("2", "Level 2 — Warrant + product samples + limited data"),
            ("3", "Level 3 — Warrant + product samples + complete data (default)"),
            ("4", "Level 4 — Warrant + per customer requirements"),
            ("5", "Level 5 — Warrant + complete data at supplier site"),
        ],
        string="Submission Level", required=True, default="3", tracking=True,
    )
    submission_reason = fields.Selection(
        [
            ("new_part", "New Part / Product"),
            ("engineering_change", "Engineering Change"),
            ("tooling_change", "Tooling Change"),
            ("correction", "Correction of Discrepancy"),
            ("re_submission", "Re-submission"),
            ("other", "Other"),
        ],
        string="Reason for Submission", required=True, default="new_part",
    )
    submission_date = fields.Date(string="Submission Date", tracking=True)

    responsible_id = fields.Many2one("res.users", string="Responsible",
                                      default=lambda self: self.env.user, tracking=True)

    # ── 18 Elements ──
    element_ids = fields.One2many("iatf.ppap.element", "submission_id", string="PPAP Elements")
    element_complete_count = fields.Integer(compute="_compute_element_stats")
    element_total_count = fields.Integer(compute="_compute_element_stats")
    progress = fields.Float(compute="_compute_element_stats", store=True)

    # ── Customer Decision ──
    customer_decision = fields.Selection(
        [
            ("approved", "Approved"),
            ("interim", "Interim Approval"),
            ("rejected", "Rejected"),
        ],
        string="Customer Decision", tracking=True,
    )
    decision_date = fields.Date(string="Decision Date")
    decision_notes = fields.Text(string="Customer Notes")

    # ── Links ──
    fmea_id = fields.Many2one("iatf.fmea", string="Related FMEA")
    control_plan_id = fields.Many2one("iatf.control.plan", string="Related Control Plan")
    apqp_project_id = fields.Many2one("iatf.apqp.project", string="APQP Project")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("preparation", "In Preparation"),
            ("submitted", "Submitted to Customer"),
            ("decided", "Customer Decided"),
            ("closed", "Closed"),
        ],
        string="Status", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("element_ids.state")
    def _compute_element_stats(self):
        for rec in self:
            total = len(rec.element_ids)
            done = len(rec.element_ids.filtered(lambda e: e.state in ("done", "na")))
            rec.element_total_count = total
            rec.element_complete_count = done
            rec.progress = (done / total * 100.0) if total else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.ppap.submission") or _("New")
        return super().create(vals_list)

    def action_start_preparation(self):
        self.write({"state": "preparation"})

    def action_submit(self):
        for rec in self:
            required_not_done = rec.element_ids.filtered(
                lambda e: e.is_required and e.state not in ("done", "na")
            )
            if required_not_done:
                raise UserError(
                    _("%d required element(s) are not complete.") % len(required_not_done)
                )
        self.write({"state": "submitted", "submission_date": fields.Date.today()})

    def action_record_decision(self):
        for rec in self:
            if not rec.customer_decision:
                raise UserError(_("Please set the Customer Decision first."))
        self.write({"state": "decided", "decision_date": fields.Date.today()})

    def action_close(self):
        self.write({"state": "closed"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_create_standard_elements(self):
        self.ensure_one()
        if self.element_ids:
            raise UserError(_("Elements already exist."))
        ELEMENTS = [
            ("1", "Design Records", True),
            ("2", "Authorized Engineering Change Documents", True),
            ("3", "Customer Engineering Approval", False),
            ("4", "DFMEA", True),
            ("5", "Process Flow Diagram", True),
            ("6", "PFMEA", True),
            ("7", "Control Plan", True),
            ("8", "Measurement System Analysis (MSA)", True),
            ("9", "Dimensional Results", True),
            ("10", "Material / Performance Test Results", True),
            ("11", "Initial Process Study (SPC)", True),
            ("12", "Qualified Laboratory Documentation", True),
            ("13", "Appearance Approval Report (AAR)", False),
            ("14", "Sample Production Parts", True),
            ("15", "Master Sample", True),
            ("16", "Checking Aids", False),
            ("17", "Customer-Specific Requirements", True),
            ("18", "Part Submission Warrant (PSW)", True),
        ]
        for num, ename, required in ELEMENTS:
            self.env["iatf.ppap.element"].create({
                "submission_id": self.id,
                "element_number": num,
                "name": ename,
                "is_required": required,
            })
        return True
