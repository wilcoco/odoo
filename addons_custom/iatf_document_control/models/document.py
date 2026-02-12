from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta


class IatfDocument(models.Model):
    _name = "iatf.document"
    _description = "Controlled Document (IATF 16949 §7.5)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "doc_number"

    # ── Identification ──
    doc_number = fields.Char(
        string="Document Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    name = fields.Char(string="Title", required=True, tracking=True)
    category_id = fields.Many2one(
        "iatf.document.category", string="Category", required=True, tracking=True,
    )
    doc_type = fields.Selection(
        [
            ("manual", "Quality Manual"),
            ("procedure", "Procedure"),
            ("instruction", "Work Instruction"),
            ("form", "Form / Template"),
            ("specification", "Specification"),
            ("standard", "External Standard"),
            ("record", "Quality Record"),
            ("other", "Other"),
        ],
        string="Document Type", required=True, default="procedure", tracking=True,
    )
    description = fields.Html(string="Description / Scope")

    # ── Ownership ──
    owner_id = fields.Many2one(
        "res.users", string="Document Owner", default=lambda self: self.env.user,
        tracking=True,
    )
    department_id = fields.Many2one("hr.department", string="Department")
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company,
    )

    # ── Revision control ──
    current_revision = fields.Char(string="Current Revision", default="00", tracking=True)
    revision_date = fields.Date(string="Revision Date", tracking=True)
    revision_ids = fields.One2many("iatf.document.revision", "document_id", string="Revision History")
    revision_count = fields.Integer(compute="_compute_revision_count")

    # ── Approval workflow ──
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review", "Under Review"),
            ("approved", "Approved"),
            ("obsolete", "Obsolete"),
        ],
        string="Status", default="draft", required=True, tracking=True,
    )
    reviewer_id = fields.Many2one("res.users", string="Reviewer", tracking=True)
    approver_id = fields.Many2one("res.users", string="Approver", tracking=True)
    review_date = fields.Date(string="Review Date")
    approval_date = fields.Date(string="Approval Date")
    next_review_date = fields.Date(
        string="Next Review Date",
        help="Periodic review date as required by IATF 16949 §7.5.3.1",
        tracking=True,
    )

    # ── Retention ──
    retention_years = fields.Integer(
        string="Retention Period (years)",
        help="How long to retain this document after obsolescence. "
             "Defaults from category if not set.",
    )
    retention_expiry = fields.Date(
        string="Retention Expiry", compute="_compute_retention_expiry", store=True,
    )

    # ── Distribution ──
    distribution_ids = fields.One2many(
        "iatf.document.distribution", "document_id", string="Distribution List",
    )

    # ── Attachments ──
    attachment_ids = fields.Many2many(
        "ir.attachment", string="Attachments",
        help="Attach the controlled document files here.",
    )
    attachment_count = fields.Integer(compute="_compute_attachment_count")

    # ── External reference ──
    external_origin = fields.Char(
        string="External Origin",
        help="For external documents: origin standard/organization (e.g. ISO, AIAG, customer)",
    )

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("doc_number_uniq", "unique(doc_number, company_id)", "Document number must be unique per company."),
    ]

    # ── Computes ──

    @api.depends("revision_ids")
    def _compute_revision_count(self):
        for doc in self:
            doc.revision_count = len(doc.revision_ids)

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        for doc in self:
            doc.attachment_count = len(doc.attachment_ids)

    @api.depends("approval_date", "retention_years", "category_id.retention_years")
    def _compute_retention_expiry(self):
        for doc in self:
            years = doc.retention_years or (doc.category_id.retention_years if doc.category_id else 0)
            if doc.approval_date and years:
                doc.retention_expiry = doc.approval_date + relativedelta(years=years)
            else:
                doc.retention_expiry = False

    # ── CRUD ──

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("doc_number", _("New")) == _("New"):
                vals["doc_number"] = self.env["ir.sequence"].next_by_code("iatf.document") or _("New")
        return super().create(vals_list)

    # ── Workflow actions ──

    def action_submit_review(self):
        for doc in self:
            if not doc.reviewer_id:
                raise UserError(_("Please assign a Reviewer before submitting for review."))
            doc.write({"state": "review", "review_date": fields.Date.today()})

    def action_approve(self):
        for doc in self:
            if not doc.approver_id:
                raise UserError(_("Please assign an Approver."))
            doc.write({
                "state": "approved",
                "approval_date": fields.Date.today(),
            })
            if not doc.next_review_date:
                doc.next_review_date = fields.Date.today() + relativedelta(years=1)

    def action_obsolete(self):
        self.write({"state": "obsolete"})

    def action_reset_draft(self):
        self.write({"state": "draft", "review_date": False, "approval_date": False})

    def action_new_revision(self):
        self.ensure_one()
        if self.state != "approved":
            raise UserError(_("Only approved documents can be revised."))
        # Create revision record for current version
        self.env["iatf.document.revision"].create({
            "document_id": self.id,
            "revision_number": self.current_revision,
            "revision_date": self.revision_date or self.approval_date or fields.Date.today(),
            "reason": _("Superseded by new revision"),
            "revised_by": self.env.user.id,
        })
        # Increment revision
        try:
            next_rev = str(int(self.current_revision) + 1).zfill(2)
        except (ValueError, TypeError):
            next_rev = self.current_revision + ".1"
        self.write({
            "current_revision": next_rev,
            "revision_date": fields.Date.today(),
            "state": "draft",
            "review_date": False,
            "approval_date": False,
        })
        return True
