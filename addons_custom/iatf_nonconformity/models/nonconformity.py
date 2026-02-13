from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfNonconformity(models.Model):
    _name = "iatf.nonconformity"
    _description = "Nonconformity Report (IATF 16949 §10.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    # ── Identification ──
    name = fields.Char(
        string="부적합 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)

    nc_type = fields.Selection(
        [
            ("internal", "내부 부적합"),
            ("supplier", "협력업체 부적합"),
            ("customer", "고객 불만"),
            ("audit", "심사 지적사항"),
            ("process", "공정 부적합"),
        ],
        string="부적합 유형", required=True, default="internal", tracking=True,
    )
    severity = fields.Selection(
        [
            ("minor", "경미"),
            ("major", "중대"),
            ("critical", "치명적"),
        ],
        string="심각도", required=True, default="minor", tracking=True,
    )
    priority = fields.Selection(
        [
            ("0", "보통"),
            ("1", "높음"),
            ("2", "긴급"),
        ],
        string="우선순위", default="0",
    )

    # ── 8D Discipline mapping ──
    # D1: Team
    team_leader_id = fields.Many2one("res.users", string="팀 리더 (D1)", tracking=True)
    team_member_ids = fields.Many2many("res.users", string="팀원 (D1)")

    # D2: Problem Description
    problem_description = fields.Html(string="문제 기술 (D2)", tracking=True)
    detection_date = fields.Date(string="발견 일자", default=fields.Date.today, required=True)
    detection_location = fields.Char(string="발견 장소")
    detected_by = fields.Many2one("res.users", string="발견자", default=lambda self: self.env.user)

    # D3: Interim Containment Action
    containment_action = fields.Html(string="격리 조치 (D3)")
    containment_date = fields.Date(string="격리 일자")
    containment_responsible_id = fields.Many2one("res.users", string="격리 담당자")
    containment_verified = fields.Boolean(string="격리 검증")

    # D4: Root Cause Analysis
    root_cause_method = fields.Selection(
        [
            ("5why", "5-Why 분석"),
            ("fishbone", "특성요인도"),
            ("fta", "결함수 분석"),
            ("other", "기타"),
        ],
        string="원인분석 방법 (D4)",
    )
    root_cause = fields.Html(string="근본 원인 (D4)")

    # D5 & D6: handled via corrective_action_ids
    # D7: Preventive Action
    preventive_action = fields.Html(string="예방/시스템 조치 (D7)")

    # D6: Verification
    verification_result = fields.Html(string="유효성 검증 (D6)")

    # D7: Preventive — already defined below

    # D8: Closure
    closure_notes = fields.Html(string="팀 인정/종료 기록 (D8)")

    # ── Timeline ──
    target_close_date = fields.Date(string="목표 종료일", tracking=True)
    actual_close_date = fields.Date(string="실제 종료일")

    # ── Responsible ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)

    notes = fields.Text(string="비고")

    # ── References ──
    product_id = fields.Many2one("product.product", string="제품")
    production_id = fields.Many2one("mrp.production", string="제조 오더")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")
    partner_id = fields.Many2one(
        "res.partner", string="관련 파트너",
        help="Customer (complaint) or Supplier (supplier NC)",
    )
    quantity_affected = fields.Float(string="영향 수량")
    quantity_rejected = fields.Float(string="불합격 수량")

    # ── Disposition ──
    disposition = fields.Selection(
        [
            ("use_as_is", "현상태 사용"),
            ("rework", "재작업"),
            ("scrap", "폐기"),
            ("return", "협력업체 반품"),
            ("sort", "전수 선별"),
            ("concession", "고객 특채"),
        ],
        string="처리 방법", tracking=True,
    )

    # ── Relations ──
    corrective_action_ids = fields.One2many(
        "iatf.corrective.action", "nonconformity_id", string="시정 조치 (D5/D6)",
    )
    corrective_action_count = fields.Integer(compute="_compute_ca_count")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="증빙 / 첨부파일")

    # ── Workflow ──
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("containment", "D3 격리"),
            ("analysis", "D4 원인분석"),
            ("corrective", "D5/D6 시정조치"),
            ("verification", "D7 검증"),
            ("closed", "D8 종료"),
            ("cancelled", "취소"),
        ],
        string="상태", default="draft", required=True, tracking=True,
    )

    company_id = fields.Many2one(
        "res.company", string="회사", default=lambda self: self.env.company,
    )

    # ── Cost tracking ──
    cost_internal = fields.Float(string="내부 비용")
    cost_external = fields.Float(string="외부 비용")
    cost_total = fields.Float(string="총 비용", compute="_compute_cost_total", store=True)

    @api.depends("cost_internal", "cost_external")
    def _compute_cost_total(self):
        for rec in self:
            rec.cost_total = rec.cost_internal + rec.cost_external

    @api.depends("corrective_action_ids")
    def _compute_ca_count(self):
        for rec in self:
            rec.corrective_action_count = len(rec.corrective_action_ids)

    # ── CRUD ──

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.nonconformity") or _("New")
        return super().create(vals_list)

    # ── Workflow actions ──

    def action_start_containment(self):
        self.write({"state": "containment"})

    def action_start_analysis(self):
        for rec in self:
            if not rec.containment_action:
                raise UserError(_("Please document the containment action (D3) before proceeding."))
        self.write({"state": "analysis"})

    def action_start_corrective(self):
        for rec in self:
            if not rec.root_cause:
                raise UserError(_("Please document the root cause (D4) before proceeding."))
        self.write({"state": "corrective"})

    def action_start_verification(self):
        for rec in self:
            if not rec.corrective_action_ids:
                raise UserError(_("Please add at least one corrective action (D5/D6)."))
        self.write({"state": "verification"})

    def action_close(self):
        for rec in self:
            open_cas = rec.corrective_action_ids.filtered(lambda ca: ca.state != "verified")
            if open_cas:
                raise UserError(
                    _("All corrective actions must be verified before closing. "
                      "%d action(s) still open.") % len(open_cas)
                )
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_view_corrective_actions(self):
        self.ensure_one()
        return {
            "name": _("Corrective Actions"),
            "type": "ir.actions.act_window",
            "res_model": "iatf.corrective.action",
            "view_mode": "list,form",
            "domain": [("nonconformity_id", "=", self.id)],
            "context": {"default_nonconformity_id": self.id},
        }
