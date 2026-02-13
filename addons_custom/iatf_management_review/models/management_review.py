from odoo import api, fields, models, _


class IatfManagementReview(models.Model):
    _name = "iatf.management.review"
    _description = "Management Review (IATF 16949 §9.3)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "meeting_date desc"

    name = fields.Char(
        string="검토 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    meeting_date = fields.Date(string="회의일", required=True, default=fields.Date.today, tracking=True)
    review_period = fields.Char(string="검토 기간", help="e.g. 2026-H1")

    chairperson_id = fields.Many2one("res.users", string="의장", required=True,
                                      default=lambda self: self.env.user, tracking=True)
    attendee_ids = fields.Many2many("res.users", string="참석자")

    # ── Inputs (§9.3.2) ──
    input_audit_results = fields.Html(string="심사 결과 요약")
    input_customer_feedback = fields.Html(string="고객 피드백 및 만족도")
    input_process_performance = fields.Html(string="공정 성과 및 제품 적합성")
    input_nc_corrective = fields.Html(string="부적합 및 시정조치")
    input_previous_actions = fields.Html(string="이전 검토 조치 현황")
    input_changes = fields.Html(string="변경사항 (내부/외부)")
    input_improvement_opportunities = fields.Html(string="개선 기회")
    input_resource_needs = fields.Html(string="자원 적절성")

    # ── IATF Supplemental Inputs (§9.3.2.1) ──
    input_cost_poor_quality = fields.Html(string="불량 비용 (COPQ)")
    input_process_effectiveness = fields.Html(string="공정 유효성 측정")
    input_product_conformity = fields.Html(string="제품 적합성 측정")
    input_warranty = fields.Html(string="보증 및 현장 반품")
    input_customer_scorecards = fields.Html(string="고객 스코어카드")
    input_field_failures = fields.Html(string="잠재적 현장 고장 (FMEA)")
    input_risk_assessment = fields.Html(string="리스크 평가 요약")

    # ── Outputs (§9.3.3) ──
    output_improvement = fields.Html(string="개선 결정")
    output_resource = fields.Html(string="자원 필요/변경")
    output_qms_changes = fields.Html(string="QMS 변경 필요사항")
    output_quality_objectives = fields.Html(string="품질 목표 갱신")
    output_other = fields.Html(string="기타 결정사항")

    # ── Action Items ──
    action_item_ids = fields.One2many("iatf.management.review.action", "review_id", string="조치 항목")
    action_count = fields.Integer(compute="_compute_action_count")
    open_action_count = fields.Integer(compute="_compute_action_count")

    state = fields.Selection(
        [
            ("planned", "계획됨"),
            ("in_progress", "진행 중"),
            ("minutes_issued", "회의록 발행"),
            ("closed", "종료"),
        ],
        string="상태", default="planned", tracking=True,
    )

    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("action_item_ids", "action_item_ids.state")
    def _compute_action_count(self):
        for rec in self:
            rec.action_count = len(rec.action_item_ids)
            rec.open_action_count = len(rec.action_item_ids.filtered(lambda a: a.state != "done"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.management.review") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_issue_minutes(self):
        self.write({"state": "minutes_issued"})

    def action_close(self):
        self.write({"state": "closed"})
