from odoo import api, fields, models, _


class IatfManagementReview(models.Model):
    _name = "iatf.management.review"
    _description = "Management Review (IATF 16949 §9.3)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
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

    def action_auto_collect_inputs(self):
        """경영검토 입력 데이터 자동 수집 (L2-16)"""
        self.ensure_one()
        from datetime import timedelta
        today = fields.Date.today()
        period_start = today - timedelta(days=180)
        parts = []

        # 심사 결과
        Audit = self.env.get("iatf.audit")
        if Audit:
            audits = Audit.search([("actual_date", ">=", period_start), ("state", "=", "closed")])
            total_findings = sum(len(a.finding_ids) for a in audits if hasattr(a, "finding_ids"))
            parts.append("<p><b>심사:</b> %d건 완료, 지적 %d건</p>" % (len(audits), total_findings))
            self.input_audit_results = "".join(parts) if parts else False

        # 고객 불만
        CC = self.env.get("iatf.customer.complaint")
        cc_parts = []
        if CC:
            complaints = CC.search([("received_date", ">=", period_start)])
            closed = complaints.filtered(lambda c: c.state == "closed")
            total_cost = sum(c.cost_total for c in complaints)
            cc_parts.append("<p><b>고객불만:</b> %d건 (종결 %d건), 총비용 %s</p>" % (
                len(complaints), len(closed), "{:,.0f}".format(total_cost)))
        self.input_customer_feedback = "".join(cc_parts) if cc_parts else False

        # 부적합/시정조치
        NC = self.env.get("iatf.nonconformity")
        nc_parts = []
        if NC:
            ncs = NC.search([("detection_date", ">=", period_start)])
            by_type = {}
            for nc in ncs:
                by_type.setdefault(nc.nc_type, 0)
                by_type[nc.nc_type] += 1
            nc_parts.append("<p><b>부적합:</b> 총 %d건 — %s</p>" % (
                len(ncs), ", ".join("%s: %d" % (k, v) for k, v in by_type.items())))
            copq = sum(nc.cost_total for nc in ncs)
            nc_parts.append("<p><b>불량비용(COPQ):</b> %s</p>" % "{:,.0f}".format(copq))
        self.input_nc_corrective = "".join(nc_parts) if nc_parts else False
        self.input_cost_poor_quality = nc_parts[-1] if len(nc_parts) > 1 else False

        # 공정 성과
        SPC = self.env.get("iatf.spc.study")
        spc_parts = []
        if SPC:
            studies = SPC.search([("state", "=", "analyzed")])
            capable = studies.filtered(lambda s: s.capability_status == "capable")
            spc_parts.append("<p><b>SPC:</b> %d건 분석, 공정능력 적합 %d건 (%.0f%%)</p>" % (
                len(studies), len(capable), len(capable) / len(studies) * 100 if studies else 0))
        self.input_process_effectiveness = "".join(spc_parts) if spc_parts else False

        # 업체 성과
        SE = self.env.get("iatf.supplier.evaluation")
        se_parts = []
        if SE:
            evals = SE.search([("evaluation_date", ">=", period_start), ("state", "=", "confirmed")])
            d_grade = evals.filtered(lambda e: e.grade == "d")
            se_parts.append("<p><b>업체 평가:</b> %d건, D등급(부적격) %d건</p>" % (len(evals), len(d_grade)))
        self.input_process_performance = "".join(se_parts) if se_parts else False

        self.message_post(body=_("경영검토 입력 데이터 자동 수집 완료"))

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_issue_minutes(self):
        self.write({"state": "minutes_issued"})

    def action_close(self):
        self.write({"state": "closed"})
