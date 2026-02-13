from odoo import api, fields, models, _


class IatfRiskRegister(models.Model):
    _name = "iatf.risk.register"
    _description = "Risk & Opportunity Register (IATF 16949 §6.1)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "risk_score desc, id"

    name = fields.Char(
        string="리스크 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    entry_type = fields.Selection(
        [("risk", "리스크"), ("opportunity", "기회")],
        string="유형", required=True, default="risk", tracking=True,
    )
    category = fields.Selection(
        [
            ("strategic", "전략적"),
            ("operational", "운영적"),
            ("quality", "품질 / 제품"),
            ("supply_chain", "공급망"),
            ("regulatory", "규제 / 준법"),
            ("financial", "재무"),
            ("environmental", "환경"),
            ("safety", "안전보건"),
            ("it", "정보보안"),
        ],
        string="카테고리", default="quality", tracking=True,
    )

    # ── Description ──
    description = fields.Html(string="리스크 / 기회 설명", required=True)
    source = fields.Char(string="발생원 / 트리거")
    affected_process = fields.Char(string="영향 공정")
    interested_parties = fields.Char(string="이해관계자")

    # ── Assessment ──
    likelihood = fields.Selection(
        [("1", "1 - Rare"), ("2", "2 - Unlikely"), ("3", "3 - Possible"),
         ("4", "4 - Likely"), ("5", "5 - Almost Certain")],
        string="발생 가능성", default="3",
    )
    impact = fields.Selection(
        [("1", "1 - Negligible"), ("2", "2 - Minor"), ("3", "3 - Moderate"),
         ("4", "4 - Major"), ("5", "5 - Catastrophic")],
        string="영향도", default="3",
    )
    risk_score = fields.Integer(
        string="리스크 점수", compute="_compute_risk_score", store=True,
        help="Likelihood × Impact",
    )
    risk_level = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        string="리스크 수준", compute="_compute_risk_score", store=True,
    )

    # ── Treatment ──
    treatment_strategy = fields.Selection(
        [
            ("avoid", "회피"),
            ("mitigate", "완화 / 감소"),
            ("transfer", "전가"),
            ("accept", "수용"),
            ("exploit", "활용 (기회)"),
        ],
        string="대응 전략", default="mitigate",
    )
    current_controls = fields.Html(string="현재 관리 수단")
    planned_actions = fields.Html(string="계획된 조치")
    responsible_id = fields.Many2one("res.users", string="리스크 소유자",
                                      default=lambda self: self.env.user, tracking=True)
    due_date = fields.Date(string="조치 기한")

    # ── Residual risk (after treatment) ──
    residual_likelihood = fields.Selection(
        [("1", "1 - Rare"), ("2", "2 - Unlikely"), ("3", "3 - Possible"),
         ("4", "4 - Likely"), ("5", "5 - Almost Certain")],
        string="잔여 발생가능성", default="1",
    )
    residual_impact = fields.Selection(
        [("1", "1 - Negligible"), ("2", "2 - Minor"), ("3", "3 - Moderate"),
         ("4", "4 - Major"), ("5", "5 - Catastrophic")],
        string="잔여 영향도", default="1",
    )
    residual_score = fields.Integer(
        string="잔여 점수", compute="_compute_residual_score", store=True,
    )

    # ── Status ──
    state = fields.Selection(
        [
            ("identified", "식별됨"),
            ("assessed", "평가 완료"),
            ("treating", "대응 중"),
            ("monitored", "모니터링"),
            ("closed", "종료"),
        ],
        string="상태", default="identified", tracking=True,
    )

    review_date = fields.Date(string="다음 검토일")
    notes = fields.Text(string="비고")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("likelihood", "impact")
    def _compute_risk_score(self):
        for rec in self:
            score = int(rec.likelihood or 0) * int(rec.impact or 0)
            rec.risk_score = score
            if score >= 20:
                rec.risk_level = "critical"
            elif score >= 12:
                rec.risk_level = "high"
            elif score >= 6:
                rec.risk_level = "medium"
            else:
                rec.risk_level = "low"

    @api.depends("residual_likelihood", "residual_impact")
    def _compute_residual_score(self):
        for rec in self:
            rec.residual_score = int(rec.residual_likelihood or 0) * int(rec.residual_impact or 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.risk.register") or _("New")
        return super().create(vals_list)

    def action_assess(self):
        self.write({"state": "assessed"})

    def action_treat(self):
        self.write({"state": "treating"})

    def action_monitor(self):
        self.write({"state": "monitored"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_reopen(self):
        self.write({"state": "assessed"})
