from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfCustomerComplaint(models.Model):
    _name = "iatf.customer.complaint"
    _description = "Customer Complaint (IATF 16949 §10.2.6)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Complaint Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Title", required=True, tracking=True)
    complaint_type = fields.Selection(
        [
            ("quality", "Quality Defect"),
            ("delivery", "Delivery Issue"),
            ("warranty", "Warranty Claim"),
            ("field_return", "Field Return / MIS"),
            ("ntr", "NTF (No Trouble Found)"),
            ("other", "Other"),
        ],
        string="Complaint Type", required=True, default="quality", tracking=True,
    )
    severity_level = fields.Selection(
        [
            ("critical", "Critical (Safety / Recall)"),
            ("major", "Major"),
            ("minor", "Minor"),
        ],
        string="Severity", default="major", tracking=True,
    )

    # ── Customer ──
    customer_id = fields.Many2one("res.partner", string="Customer", required=True, tracking=True)
    customer_ref = fields.Char(string="Customer Reference #")
    received_date = fields.Date(string="Date Received", default=fields.Date.today, required=True)
    response_due_date = fields.Date(string="Response Due Date", tracking=True)

    # ── Product / Lot ──
    product_id = fields.Many2one("product.product", string="Product")
    part_number = fields.Char(string="Part Number")
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial")
    quantity_affected = fields.Float(string="Qty Affected")
    quantity_returned = fields.Float(string="Qty Returned")

    # ── Problem description ──
    problem_description = fields.Html(string="Problem Description", required=True)
    failure_mode = fields.Char(string="Failure Mode")
    customer_impact = fields.Html(string="Customer Impact")

    # ── Containment ──
    containment_action = fields.Html(string="Immediate Containment Action")
    containment_date = fields.Date(string="Containment Date")

    # ── Root cause & corrective action ──
    root_cause = fields.Html(string="Root Cause Analysis")
    corrective_action = fields.Html(string="Corrective Action")
    preventive_action = fields.Html(string="Preventive Action")
    verification_result = fields.Html(string="Verification of Effectiveness")

    # ── Links ──
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="Linked NC / 8D")

    # ── Costs ──
    cost_sorting = fields.Float(string="Sorting Cost")
    cost_rework = fields.Float(string="Rework Cost")
    cost_scrap = fields.Float(string="Scrap Cost")
    cost_freight = fields.Float(string="Premium Freight Cost")
    cost_warranty = fields.Float(string="Warranty Cost")
    cost_total = fields.Float(string="Total Cost", compute="_compute_cost_total", store=True)

    # ── Status ──
    responsible_id = fields.Many2one("res.users", string="Responsible",
                                      default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(
        [
            ("new", "New"),
            ("containment", "Containment"),
            ("analysis", "Root Cause Analysis"),
            ("corrective", "Corrective Action"),
            ("verification", "Verification"),
            ("closed", "Closed"),
        ],
        string="Status", default="new", tracking=True,
    )

    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("cost_sorting", "cost_rework", "cost_scrap", "cost_freight", "cost_warranty")
    def _compute_cost_total(self):
        for rec in self:
            rec.cost_total = (rec.cost_sorting + rec.cost_rework + rec.cost_scrap
                              + rec.cost_freight + rec.cost_warranty)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.customer.complaint") or _("New")
        return super().create(vals_list)

    def action_containment(self):
        self.write({"state": "containment"})

    def action_analysis(self):
        self.write({"state": "analysis"})

    def action_corrective(self):
        self.write({"state": "corrective"})

    def action_verification(self):
        self.write({"state": "verification"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_create_nc(self):
        self.ensure_one()
        nc = self.env["iatf.nonconformity"].create({
            "title": _("Customer Complaint: %s") % self.title,
            "nc_type": "customer",
            "severity": self.severity_level if self.severity_level != "critical" else "major",
            "problem_description": self.problem_description,
        })
        self.nonconformity_id = nc.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.nonconformity",
            "res_id": nc.id,
            "view_mode": "form",
            "target": "current",
        }
