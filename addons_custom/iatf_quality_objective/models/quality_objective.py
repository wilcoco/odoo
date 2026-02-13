from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfQualityObjective(models.Model):
    _name = "iatf.quality.objective"
    _description = "품질 목표 (IATF 16949 §6.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "year desc, sequence"

    name = fields.Char(
        string="목표 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="목표명", required=True, tracking=True)
    year = fields.Char(string="대상 연도", required=True, default=lambda self: str(fields.Date.today().year))
    category = fields.Selection(
        [
            ("customer", "고객 만족"),
            ("quality", "품질 성과"),
            ("delivery", "납기 성과"),
            ("cost", "비용 / COPQ"),
            ("process", "공정 성과"),
            ("safety", "안전/환경"),
            ("supplier", "협력업체 품질"),
            ("other", "기타"),
        ],
        string="카테고리", required=True, default="quality", tracking=True,
    )
    description = fields.Html(string="목표 설명")
    sequence = fields.Integer(default=10)

    # ── KPI 정의 ──
    kpi_name = fields.Char(string="KPI 지표명", required=True)
    kpi_unit = fields.Char(string="단위", help="예: %, PPM, 건, 점")
    baseline_value = fields.Float(string="기준값 (전년도)")
    target_value = fields.Float(string="목표값", required=True)
    stretch_target = fields.Float(string="도전 목표값")

    # ── 실적 ──
    actual_q1 = fields.Float(string="1분기 실적")
    actual_q2 = fields.Float(string="2분기 실적")
    actual_q3 = fields.Float(string="3분기 실적")
    actual_q4 = fields.Float(string="4분기 실적")
    actual_ytd = fields.Float(string="연간 누적", compute="_compute_ytd", store=True)
    achievement_rate = fields.Float(string="달성률 (%)", compute="_compute_achievement", store=True)

    # ── 방향 ──
    direction = fields.Selection(
        [("higher", "높을수록 좋음"), ("lower", "낮을수록 좋음")],
        string="방향", default="higher", required=True,
    )
    achievement_status = fields.Selection(
        [
            ("on_track", "달성 중"),
            ("at_risk", "위험"),
            ("behind", "미달"),
            ("achieved", "달성"),
        ],
        string="달성 현황", compute="_compute_achievement", store=True,
    )

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    department_id = fields.Many2one("hr.department", string="부서")

    # ── 조치 계획 ──
    action_plan = fields.Html(string="실행 계획")
    review_notes = fields.Html(string="검토 기록")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("active", "활성"),
            ("review", "검토 중"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("actual_q1", "actual_q2", "actual_q3", "actual_q4")
    def _compute_ytd(self):
        for rec in self:
            values = [v for v in [rec.actual_q1, rec.actual_q2, rec.actual_q3, rec.actual_q4] if v]
            rec.actual_ytd = sum(values) / len(values) if values else 0.0

    @api.depends("actual_ytd", "target_value", "direction")
    def _compute_achievement(self):
        for rec in self:
            if rec.target_value:
                rec.achievement_rate = (rec.actual_ytd / rec.target_value) * 100.0
            else:
                rec.achievement_rate = 0.0

            if not rec.actual_ytd:
                rec.achievement_status = "behind"
            elif rec.direction == "higher":
                if rec.actual_ytd >= rec.target_value:
                    rec.achievement_status = "achieved"
                elif rec.actual_ytd >= rec.target_value * 0.9:
                    rec.achievement_status = "on_track"
                elif rec.actual_ytd >= rec.target_value * 0.7:
                    rec.achievement_status = "at_risk"
                else:
                    rec.achievement_status = "behind"
            else:  # lower is better
                if rec.actual_ytd <= rec.target_value:
                    rec.achievement_status = "achieved"
                elif rec.actual_ytd <= rec.target_value * 1.1:
                    rec.achievement_status = "on_track"
                elif rec.actual_ytd <= rec.target_value * 1.3:
                    rec.achievement_status = "at_risk"
                else:
                    rec.achievement_status = "behind"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.quality.objective") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_review(self):
        self.write({"state": "review"})

    def action_close(self):
        self.write({"state": "closed"})
