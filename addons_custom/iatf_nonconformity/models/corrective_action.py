from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfCorrectiveAction(models.Model):
    _name = "iatf.corrective.action"
    _description = "Corrective / Preventive Action (IATF 16949 §10.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="CA Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    nonconformity_id = fields.Many2one(
        "iatf.nonconformity", string="Nonconformity", required=True,
        ondelete="cascade", index=True, tracking=True,
    )
    ca_type = fields.Selection(
        [
            ("correction", "Correction (immediate fix)"),
            ("corrective", "Corrective Action (eliminate root cause)"),
            ("preventive", "Preventive Action (prevent recurrence)"),
        ],
        string="Action Type", required=True, default="corrective", tracking=True,
    )
    description = fields.Html(string="Action Description", required=True)
    responsible_id = fields.Many2one("res.users", string="Responsible", required=True, tracking=True)
    due_date = fields.Date(string="Due Date", required=True, tracking=True)
    completion_date = fields.Date(string="Completion Date")

    # ── Verification ──
    verification_method = fields.Text(string="Verification Method")
    verification_result = fields.Html(string="Verification Result")
    verified_by = fields.Many2one("res.users", string="Verified By")
    verification_date = fields.Date(string="Verification Date")
    effective = fields.Selection(
        [
            ("yes", "Effective"),
            ("no", "Not Effective"),
            ("partial", "Partially Effective"),
        ],
        string="Effectiveness", tracking=True,
    )

    # ── Status ──
    state = fields.Selection(
        [
            ("open", "Open"),
            ("in_progress", "In Progress"),
            ("implemented", "Implemented"),
            ("verified", "Verified"),
            ("closed", "Closed"),
        ],
        string="Status", default="open", required=True, tracking=True,
    )

    attachment_ids = fields.Many2many("ir.attachment", string="Evidence")
    company_id = fields.Many2one(
        "res.company", string="Company", related="nonconformity_id.company_id", store=True,
    )

    is_overdue = fields.Boolean(compute="_compute_is_overdue", store=True)

    @api.depends("due_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = (
                rec.due_date and rec.due_date < today and rec.state not in ("verified", "closed")
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.corrective.action") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_implement(self):
        self.write({"state": "implemented", "completion_date": fields.Date.today()})

    def action_verify(self):
        for rec in self:
            if not rec.effective:
                raise UserError(_("Please set the Effectiveness evaluation before verifying."))
        self.write({
            "state": "verified",
            "verified_by": self.env.user.id,
            "verification_date": fields.Date.today(),
        })

    def action_close(self):
        for rec in self:
            if rec.state != "verified":
                raise UserError(_("Action must be verified before closing."))
        self.write({"state": "closed"})

    def action_reopen(self):
        self.write({"state": "open", "effective": False, "verified_by": False, "verification_date": False})
