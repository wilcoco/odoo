from odoo import api, fields, models, _


class IatfContingencyPlan(models.Model):
    _name = "iatf.contingency.plan"
    _description = "Contingency Plan (IATF 16949 §6.1.2.3)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="계획 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    plan_type = fields.Selection(
        [
            ("supply", "공급망 중단"),
            ("equipment", "주요 설비 고장"),
            ("labor", "인력 부족"),
            ("utility", "유틸리티 중단 (전기/수도/가스)"),
            ("it", "IT 시스템 / 사이버 장애"),
            ("natural", "자연재해"),
            ("logistics", "물류 / 운송"),
            ("pandemic", "팬데믹 / 보건 비상"),
            ("other", "기타"),
        ],
        string="계획 유형", required=True, default="equipment", tracking=True,
    )
    risk_description = fields.Html(string="위험 / 위협 설명", required=True)

    # ── Impact ──
    affected_process = fields.Char(string="영향 공정")
    affected_product_ids = fields.Many2many("product.product", string="영향 제품")
    impact_severity = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        string="영향 심각도", default="medium",
    )
    estimated_downtime = fields.Char(string="예상 중단 시간")

    # ── Prevention & Response ──
    prevention_measures = fields.Html(string="예방 / 완화 조치")
    response_actions = fields.Html(string="대응 조치")
    recovery_actions = fields.Html(string="복구 조치")
    communication_plan = fields.Html(string="커뮤니케이션 계획")
    alternate_source = fields.Char(string="대체 공급원 / 백업")

    # ── Validation ──
    last_test_date = fields.Date(string="최근 훈련일")
    test_frequency = fields.Char(string="훈련 주기", help="e.g. Annual, Semi-annual")
    test_result = fields.Html(string="최근 훈련 결과")
    next_test_date = fields.Date(string="다음 훈련 예정일")

    # ── Ownership ──
    responsible_id = fields.Many2one("res.users", string="계획 담당자",
                                      default=lambda self: self.env.user, tracking=True)
    team_member_ids = fields.Many2many("res.users", string="대응팀")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("active", "활성"),
            ("activated", "발동됨"),
            ("review", "검토 중"),
            ("obsolete", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )

    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.contingency.plan") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_trigger(self):
        self.write({"state": "activated"})

    def action_deactivate(self):
        self.write({"state": "active"})

    def action_review(self):
        self.write({"state": "review"})

    def action_obsolete(self):
        self.write({"state": "obsolete"})

    def action_reset_draft(self):
        self.write({"state": "draft"})
