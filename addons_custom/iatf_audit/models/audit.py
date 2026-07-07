from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfAudit(models.Model):
    _name = "iatf.audit"
    _description = "Internal Audit (IATF 16949 §9.2)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "planned_date desc"

    name = fields.Char(
        string="심사 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="심사 제목", required=True, tracking=True)
    audit_type = fields.Selection(
        [
            ("system", "QMS / 시스템 심사"),
            ("process", "공정 심사 (VDA 6.3)"),
            ("product", "제품 심사"),
            ("supplier", "협력업체 심사"),
        ],
        string="심사 유형", required=True, default="system", tracking=True,
    )

    # ── Planning ──
    planned_date = fields.Date(string="계획일", required=True, tracking=True)
    actual_date = fields.Date(string="실제 일자")
    department_id = fields.Many2one("hr.department", string="피심사 부서")
    process_name = fields.Char(string="피심사 공정")
    standard_reference = fields.Char(
        string="표준 / 조항 참조",
        help="e.g. IATF 16949 §8.5, VDA 6.3 P5-P7",
    )

    # ── Auditors ──
    lead_auditor_id = fields.Many2one("res.users", string="수석 심사원", required=True, tracking=True)
    auditor_ids = fields.Many2many("res.users", string="심사팀")

    # ── Findings ──
    finding_ids = fields.One2many("iatf.audit.finding", "audit_id", string="지적사항")
    finding_count = fields.Integer(compute="_compute_finding_count", store=True)
    nc_major_count = fields.Integer(string="중대 부적합", compute="_compute_finding_count", store=True)
    nc_minor_count = fields.Integer(string="경미 부적합", compute="_compute_finding_count", store=True)
    observation_count = fields.Integer(string="관찰사항", compute="_compute_finding_count", store=True)

    # ── Score (for VDA 6.3) ──
    vda_score = fields.Float(string="VDA 6.3 점수 (%)", digits=(5, 1))
    vda_grade = fields.Selection(
        [
            ("a", "A (≥ 90%)"),
            ("b", "B (80–89%)"),
            ("c", "C (< 80%)"),
        ],
        string="VDA 등급",
    )

    # ── Status ──
    state = fields.Selection(
        [
            ("planned", "계획됨"),
            ("in_progress", "진행 중"),
            ("report", "보고서 발행"),
            ("follow_up", "후속 조치"),
            ("closed", "종료"),
            ("cancelled", "취소"),
        ],
        string="상태", default="planned", tracking=True,
    )
    audit_report = fields.Html(string="심사 보고서 / 요약")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("finding_ids", "finding_ids.finding_type")
    def _compute_finding_count(self):
        for audit in self:
            findings = audit.finding_ids
            audit.finding_count = len(findings)
            audit.nc_major_count = len(findings.filtered(lambda f: f.finding_type == "major"))
            audit.nc_minor_count = len(findings.filtered(lambda f: f.finding_type == "minor"))
            audit.observation_count = len(findings.filtered(lambda f: f.finding_type == "observation"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.audit") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "in_progress", "actual_date": fields.Date.today()})

    def action_issue_report(self):
        self.write({"state": "report"})

    def action_follow_up(self):
        self.write({"state": "follow_up"})

    def action_close(self):
        for audit in self:
            open_findings = audit.finding_ids.filtered(lambda f: f.state != "closed")
            if open_findings:
                raise UserError(_("%d finding(s) still open.") % len(open_findings))
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})
