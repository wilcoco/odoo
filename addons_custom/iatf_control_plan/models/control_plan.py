from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfControlPlan(models.Model):
    _name = "iatf.control.plan"
    _description = "Control Plan (IATF 16949 §8.5.1.1)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="CP Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Title", required=True, tracking=True)
    cp_type = fields.Selection(
        [
            ("prototype", "Prototype"),
            ("pre_launch", "Pre-Launch"),
            ("production", "Production"),
        ],
        string="Control Plan Type", required=True, default="production", tracking=True,
    )

    product_id = fields.Many2one("product.product", string="Product")
    part_number = fields.Char(string="Part Number")
    customer_id = fields.Many2one("res.partner", string="Customer")
    revision = fields.Char(string="Revision", default="01")
    revision_date = fields.Date(string="Revision Date", default=fields.Date.today)

    responsible_id = fields.Many2one("res.users", string="Owner",
                                      default=lambda self: self.env.user, tracking=True)
    team_member_ids = fields.Many2many("res.users", string="Core Team")

    fmea_id = fields.Many2one("iatf.fmea", string="Related FMEA")
    apqp_project_id = fields.Many2one("iatf.apqp.project", string="APQP Project")
    document_ids = fields.Many2many("iatf.document", string="Related Documents")

    line_ids = fields.One2many("iatf.control.plan.line", "control_plan_id", string="Control Plan Lines")
    line_count = fields.Integer(compute="_compute_line_count")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review", "Under Review"),
            ("approved", "Approved"),
            ("obsolete", "Obsolete"),
        ],
        string="Status", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.control.plan") or _("New")
        return super().create(vals_list)

    def action_submit_review(self):
        self.write({"state": "review"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_obsolete(self):
        self.write({"state": "obsolete"})

    def action_reset_draft(self):
        self.write({"state": "draft"})
