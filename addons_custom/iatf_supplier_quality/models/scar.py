from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfScar(models.Model):
    _name = "iatf.scar"
    _description = "Supplier Corrective Action Request (SCAR)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="SCAR Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    supplier_id = fields.Many2one("res.partner", string="Supplier", required=True,
                                   domain="[('supplier_rank','>',0)]", tracking=True)
    issue_date = fields.Date(string="Issue Date", default=fields.Date.today, required=True)
    response_due_date = fields.Date(string="Response Due Date", required=True, tracking=True)

    # ── Problem ──
    product_id = fields.Many2one("product.product", string="Affected Product")
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial")
    quantity_affected = fields.Float(string="Qty Affected")
    problem_description = fields.Html(string="Problem Description", required=True)
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="Related NC")

    # ── Supplier response ──
    containment_action = fields.Html(string="Containment Action (Supplier)")
    root_cause = fields.Html(string="Root Cause (Supplier)")
    corrective_action = fields.Html(string="Corrective Action (Supplier)")
    preventive_action = fields.Html(string="Preventive Action (Supplier)")
    response_date = fields.Date(string="Response Received Date")

    # ── Verification ──
    verification_result = fields.Html(string="Verification Result")
    verified_by = fields.Many2one("res.users", string="Verified By")
    effective = fields.Selection(
        [("yes", "Effective"), ("no", "Not Effective"), ("partial", "Partially Effective")],
        string="Effectiveness",
    )

    responsible_id = fields.Many2one("res.users", string="Internal Responsible",
                                      default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("issued", "Issued to Supplier"),
            ("response", "Response Received"),
            ("verification", "Verification"),
            ("closed", "Closed"),
        ],
        default="draft", tracking=True,
    )
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.scar") or _("New")
        return super().create(vals_list)

    def action_issue(self):
        self.write({"state": "issued"})

    def action_receive_response(self):
        self.write({"state": "response", "response_date": fields.Date.today()})

    def action_verify(self):
        self.write({"state": "verification"})

    def action_close(self):
        for rec in self:
            if not rec.effective:
                raise UserError(_("Please set the effectiveness evaluation before closing."))
        self.write({"state": "closed"})
