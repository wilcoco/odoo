from odoo import api, fields, models, _
from .sq_criteria import EVIDENCE_DATE_FIELD

# 이행상태 → 점수배율 (참고 엑셀 실측: 양호0.8·보완0.6·일부미흡0.5·다수미흡0.25)
STATUS_RATIO = {
    "excellent": 1.0,    # 우수
    "good": 0.8,         # 양호
    "supplement": 0.6,   # 보완
    "partial_poor": 0.5, # 일부미흡
    "many_poor": 0.25,   # 다수미흡
    "poor": 0.0,         # 미흡
    # "na" 해당없음 → 분모에서 제외
}
STATUS_SELECTION = [
    ("excellent", "우수"),
    ("good", "양호"),
    ("supplement", "보완"),
    ("partial_poor", "일부미흡"),
    ("many_poor", "다수미흡"),
    ("poor", "미흡"),
    ("na", "해당없음"),
]


class SqEvaluation(models.Model):
    _name = "sq.evaluation"
    _description = "SQ 평가 (자가/수감 대비)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "evaluation_date desc, id desc"

    name = fields.Char(string="평가 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    title = fields.Char(string="평가명", required=True, tracking=True)
    evaluation_date = fields.Date(string="평가일", default=fields.Date.today, required=True, tracking=True)
    framework = fields.Selection(
        [("sq", "SQ"), ("iatf", "IATF 16949")],
        string="평가체계", default="sq", required=True, tracking=True,
    )
    eval_type = fields.Selection(
        [("self", "자가평가"), ("pre_audit", "수감 사전점검"), ("regular", "정기"), ("new_cert", "신규인증")],
        string="평가 구분", default="self", tracking=True,
    )
    industry = fields.Char(string="업종", help="예: PL사출")
    evaluator_id = fields.Many2one("res.users", string="평가 담당", default=lambda self: self.env.user)
    host_org = fields.Char(string="주관장/고객", help="예: HKMC / 상위 협력사")
    period_start = fields.Date(string="증빙 기간 시작", help="비우면 전체 기간 증빙 조회")
    period_end = fields.Date(string="증빙 기간 종료")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    line_ids = fields.One2many("sq.evaluation.line", "evaluation_id", string="평가 항목")

    total_max_score = fields.Float(string="배점(해당분)", compute="_compute_scores", store=True)
    total_score = fields.Float(string="취득점수", compute="_compute_scores", store=True)
    score_pct = fields.Float(string="달성률 (%)", compute="_compute_scores", store=True, digits=(5, 1))
    grade = fields.Char(string="등급", compute="_compute_scores", store=True,
                        help="자체 평가 등급표(sq.grade, 설정>등급표) 기반 자동등급")
    grade_label = fields.Char(string="판정", compute="_compute_scores", store=True)
    na_count = fields.Integer(string="해당없음 수", compute="_compute_scores", store=True)

    summary_opinion = fields.Text(string="종합 의견")
    main_problems = fields.Text(string="주요 문제점")
    improvements = fields.Text(string="개선 사항")

    state = fields.Selection(
        [("draft", "초안"), ("in_progress", "평가중"), ("done", "완료"), ("confirmed", "확정")],
        string="상태", default="draft", tracking=True,
    )

    @api.depends("line_ids.score", "line_ids.effective_max", "framework")
    def _compute_scores(self):
        for rec in self:
            tmax = sum(rec.line_ids.mapped("effective_max"))
            tscore = sum(rec.line_ids.mapped("score"))
            rec.total_max_score = tmax
            rec.total_score = tscore
            rec.score_pct = (tscore / tmax * 100.0) if tmax else 0.0
            rec.na_count = len(rec.line_ids.filtered(lambda l: l.status == "na"))
            rec.grade, rec.grade_label = rec._grade_from_pct(rec.score_pct)

    def _grade_from_pct(self, pct):
        """자체 평가 등급표(sq.grade) 조회 — 높은 하한부터 판정. 표 비어있으면 '-'."""
        grades = self.env["sq.grade"].search(
            [("framework", "=", self.framework)], order="min_pct desc")
        for g in grades:
            if pct >= g.min_pct:
                return g.name, g.label or ""
        if grades:  # 모든 하한 미만 → 최하 등급
            last = grades[-1]
            return last.name, last.label or ""
        return "-", ""

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("sq.evaluation") or _("New")
        return super().create(vals_list)

    def action_load_criteria(self):
        """평가체계(SQ/IATF)에 해당하는 활성 기준 템플릿을 평가 라인으로 로드."""
        self.ensure_one()
        self.line_ids.unlink()
        crits = self.env["sq.criteria"].search([
            ("active", "=", True), ("framework", "=", self.framework)])
        self.env["sq.evaluation.line"].create([
            {"evaluation_id": self.id, "criteria_id": c.id} for c in crits
        ])
        self.state = "in_progress"
        return True

    def action_done(self):
        self.write({"state": "done"})

    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_reset_draft(self):
        self.write({"state": "draft"})


class SqEvaluationLine(models.Model):
    _name = "sq.evaluation.line"
    _description = "SQ 평가 항목 결과"
    _inherit = ["sq.evidence.mixin"]
    _order = "sequence, id"

    evaluation_id = fields.Many2one("sq.evaluation", string="평가", required=True, ondelete="cascade", index=True)
    criteria_id = fields.Many2one("sq.criteria", string="기준 항목", required=True)
    sequence = fields.Integer(related="criteria_id.sequence", store=True)
    category_id = fields.Many2one(related="criteria_id.category_id", store=True, string="대분류")
    code = fields.Char(related="criteria_id.code", store=True, string="No")
    name = fields.Char(related="criteria_id.name", store=True, string="세부항목")
    description = fields.Text(related="criteria_id.description", string="점검 상세")
    max_score = fields.Integer(related="criteria_id.max_score", store=True, string="배점")
    evidence_source = fields.Selection(related="criteria_id.evidence_source", store=True)

    status = fields.Selection(STATUS_SELECTION, string="이행상태")
    ratio = fields.Float(string="배율", compute="_compute_score", store=True, digits=(3, 2))
    score = fields.Float(string="평가점수", compute="_compute_score", store=True, digits=(6, 2))
    effective_max = fields.Float(string="유효배점", compute="_compute_score", store=True,
                                 help="해당없음이면 0 (분모 제외)")
    observation = fields.Text(string="지적 및 관찰사항")
    additional_finding = fields.Text(string="추가 지적사항")

    def _evidence_domain(self):
        """super(기준 스코프: field_record) + 평가서 기간(period)로 증빙 스코프."""
        domain = super()._evidence_domain()
        ev = self.evaluation_id
        date_field = EVIDENCE_DATE_FIELD.get(self.evidence_source)
        model, _label = self._evidence_target()
        if date_field and model and date_field in self.env[model]._fields:
            if ev.period_start:
                domain.append((date_field, ">=", ev.period_start))
            if ev.period_end:
                domain.append((date_field, "<=", ev.period_end))
        return domain

    @api.depends("status", "max_score")
    def _compute_score(self):
        for rec in self:
            if rec.status == "na" or not rec.status:
                rec.ratio = 0.0
                rec.score = 0.0
                rec.effective_max = 0.0 if rec.status == "na" else float(rec.max_score or 0)
            else:
                rec.ratio = STATUS_RATIO.get(rec.status, 0.0)
                rec.score = (rec.max_score or 0) * rec.ratio
                rec.effective_max = float(rec.max_score or 0)
