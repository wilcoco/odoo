from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfFmea(models.Model):
    _name = "iatf.fmea"
    _description = "FMEA Document (IATF 16949 §8.3.5)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="FMEA 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    fmea_type = fields.Selection(
        [
            ("dfmea", "DFMEA (설계)"),
            ("pfmea", "PFMEA (공정)"),
        ],
        string="FMEA 유형", required=True, default="pfmea", tracking=True,
    )

    # ── Header info (AIAG-VDA FMEA format) ──
    product_id = fields.Many2one("product.product", string="제품")
    part_number = fields.Char(string="부품 번호")
    process_name = fields.Char(string="공정 / 시스템명")
    customer_id = fields.Many2one("res.partner", string="고객")
    model_year = fields.Char(string="모델연도 / 프로그램")

    # ── Team ──
    responsible_id = fields.Many2one("res.users", string="FMEA 담당자",
                                      default=lambda self: self.env.user, tracking=True)
    team_member_ids = fields.Many2many("res.users", string="핵심 팀원")

    # ── Revision ──
    revision = fields.Char(string="개정", default="01")
    revision_date = fields.Date(string="개정일", default=fields.Date.today)

    # ── FMEA Lines ──
    line_ids = fields.One2many("iatf.fmea.line", "fmea_id", string="FMEA 항목")
    line_count = fields.Integer(compute="_compute_line_count")

    # ── Status ──
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("in_progress", "진행 중"),
            ("review", "검토 중"),
            ("approved", "승인됨"),
        ],
        string="상태", default="draft", tracking=True,
    )

    # ── Statistics ──
    max_rpn = fields.Integer(string="최고 RPN", compute="_compute_stats", store=True)
    high_risk_count = fields.Integer(string="고위험 항목", compute="_compute_stats", store=True)
    open_action_count = fields.Integer(string="미결 조치", compute="_compute_stats", store=True)

    # ── Links ──
    apqp_project_id = fields.Many2one("iatf.apqp.project", string="APQP 프로젝트")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends("line_ids.rpn", "line_ids.action_priority", "line_ids.action_status")
    def _compute_stats(self):
        for rec in self:
            lines = rec.line_ids
            rec.max_rpn = max(lines.mapped("rpn") or [0])
            rec.high_risk_count = len(lines.filtered(lambda l: l.action_priority == "high"))
            rec.open_action_count = len(lines.filtered(
                lambda l: l.action_status in ("open", "in_progress")
            ))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.fmea") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_submit_review(self):
        self.write({"state": "review"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_reset_draft(self):
        self.write({"state": "draft"})
