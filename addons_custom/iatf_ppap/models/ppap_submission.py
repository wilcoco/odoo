from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfPpapSubmission(models.Model):
    _name = "iatf.ppap.submission"
    _description = "PPAP Submission (IATF 16949 §8.3.4.4)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="PPAP 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    product_id = fields.Many2one("product.product", string="제품", tracking=True)
    part_number = fields.Char(string="부품 번호")
    customer_id = fields.Many2one("res.partner", string="고객", tracking=True)

    submission_level = fields.Selection(
        [
            ("1", "Level 1 — Warrant + limited data"),
            ("2", "Level 2 — Warrant + product samples + limited data"),
            ("3", "Level 3 — Warrant + product samples + complete data (default)"),
            ("4", "Level 4 — Warrant + per customer requirements"),
            ("5", "Level 5 — Warrant + complete data at supplier site"),
        ],
        string="제출 수준", required=True, default="3", tracking=True,
    )
    submission_reason = fields.Selection(
        [
            ("new_part", "신규 부품/제품"),
            ("engineering_change", "설계 변경"),
            ("tooling_change", "금형 변경"),
            ("correction", "불일치 수정"),
            ("re_submission", "재제출"),
            ("other", "기타"),
        ],
        string="제출 사유", required=True, default="new_part",
    )
    submission_date = fields.Date(string="제출일", tracking=True)

    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)

    # ── 18 Elements ──
    element_ids = fields.One2many("iatf.ppap.element", "submission_id", string="PPAP 요소")
    element_complete_count = fields.Integer(compute="_compute_element_stats")
    element_total_count = fields.Integer(compute="_compute_element_stats")
    progress = fields.Float(compute="_compute_element_stats", store=True)

    # ── Customer Decision ──
    customer_decision = fields.Selection(
        [
            ("approved", "승인"),
            ("interim", "잠정 승인"),
            ("rejected", "반려"),
        ],
        string="고객 결정", tracking=True,
    )
    decision_date = fields.Date(string="결정일")
    decision_notes = fields.Text(string="고객 비고")

    # ── Links ──
    fmea_id = fields.Many2one("iatf.fmea", string="관련 FMEA")
    control_plan_id = fields.Many2one("iatf.control.plan", string="관련 관리계획서")
    apqp_project_id = fields.Many2one("iatf.apqp.project", string="APQP 프로젝트")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("preparation", "준비 중"),
            ("submitted", "고객 제출"),
            ("decided", "고객 결정완료"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
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
            if not rec.customer_id:
                raise UserError(_("Please set the Customer first."))
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
