from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfApqpProject(models.Model):
    _name = "iatf.apqp.project"
    _description = "APQP Project (IATF 16949 §8.3)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="Project Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="Project Title", required=True, tracking=True)
    description = fields.Html(string="Description")

    # ── Product / Customer ──
    product_id = fields.Many2one("product.product", string="Product")
    customer_id = fields.Many2one("res.partner", string="Customer", tracking=True)
    part_number = fields.Char(string="Part Number")

    # ── Team ──
    project_leader_id = fields.Many2one("res.users", string="Project Leader",
                                         default=lambda self: self.env.user, tracking=True)
    team_member_ids = fields.Many2many("res.users", string="Team Members")

    # ── Timeline ──
    date_start = fields.Date(string="Start Date", tracking=True)
    date_target_sop = fields.Date(string="Target SOP Date",
                                   help="Start of Production target date", tracking=True)
    date_actual_sop = fields.Date(string="Actual SOP Date")

    # ── Phases ──
    phase_ids = fields.One2many("iatf.apqp.phase", "project_id", string="APQP Phases")
    current_phase = fields.Selection(
        [
            ("1", "Phase 1: Plan & Define"),
            ("2", "Phase 2: Product Design & Dev"),
            ("3", "Phase 3: Process Design & Dev"),
            ("4", "Phase 4: Product & Process Validation"),
            ("5", "Phase 5: Production"),
        ],
        string="Current Phase", compute="_compute_current_phase", store=True,
    )
    progress = fields.Float(string="Overall Progress (%)", compute="_compute_progress", store=True)

    # ── Status ──
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("on_hold", "On Hold"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status", default="draft", tracking=True,
    )

    # ── Links ──
    document_ids = fields.Many2many("iatf.document", string="Related Documents")
    odoo_project_id = fields.Many2one("project.project", string="Linked Odoo Project")

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("phase_ids.state")
    def _compute_current_phase(self):
        for proj in self:
            active_phases = proj.phase_ids.filtered(lambda p: p.state == "in_progress")
            if active_phases:
                proj.current_phase = active_phases[0].phase_number
            else:
                not_started = proj.phase_ids.filtered(lambda p: p.state == "not_started")
                proj.current_phase = not_started[0].phase_number if not_started else "5"

    @api.depends("phase_ids.progress")
    def _compute_progress(self):
        for proj in self:
            phases = proj.phase_ids
            if phases:
                proj.progress = sum(phases.mapped("progress")) / len(phases)
            else:
                proj.progress = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.apqp.project") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_hold(self):
        self.write({"state": "on_hold"})

    def action_complete(self):
        for proj in self:
            incomplete = proj.phase_ids.filtered(lambda p: p.state != "completed")
            if incomplete:
                raise UserError(
                    _("All phases must be completed. %d phase(s) remain.") % len(incomplete)
                )
        self.write({"state": "completed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_create_phases_from_template(self):
        self.ensure_one()
        if self.phase_ids:
            raise UserError(_("Phases already exist. Delete them first to re-create from template."))
        template_phases = self.env["iatf.apqp.phase.template"].search([], order="phase_number")
        for tmpl in template_phases:
            phase = self.env["iatf.apqp.phase"].create({
                "project_id": self.id,
                "phase_number": tmpl.phase_number,
                "name": tmpl.name,
                "description": tmpl.description,
            })
            for del_tmpl in tmpl.deliverable_template_ids:
                self.env["iatf.apqp.deliverable"].create({
                    "phase_id": phase.id,
                    "name": del_tmpl.name,
                    "description": del_tmpl.description,
                    "is_required": del_tmpl.is_required,
                })
        return True
