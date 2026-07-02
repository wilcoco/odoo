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

    # ── 증빙 기반 자동채점 (명세 3-2/3-4) ──
    def action_auto_propose(self):
        """전 라인 증빙 자동채점 → proposed_status 제안 (확정 status는 안 건드림)."""
        for rec in self:
            auto = manual = 0
            for line in rec.line_ids:
                st, reason = line._auto_propose()
                line.write({
                    "proposed_status": st or False,
                    "proposed_reason": reason,
                    "auto_scored": bool(st),
                })
                auto += 1 if st else 0
                manual += 0 if st else 1
            weak = len(rec.line_ids.filtered(
                lambda l: l.proposed_status in ("supplement", "partial_poor", "many_poor", "poor")))
            rec.message_post(body=_(
                "증빙 기반 자동채점: 제안 %(a)s건 / 수기대상 %(m)s건 / <b>보강 필요 %(w)s건</b>"
            ) % {"a": auto, "m": manual, "w": weak})
        return True

    def action_apply_proposal(self):
        """제안값 일괄 확정 — 심사자가 아직 판정 안 한(빈) 라인만 status ← proposed.
        이미 수기 확정된 라인은 보존(자동이 확정을 덮지 않음)."""
        for rec in self:
            targets = rec.line_ids.filtered(lambda l: l.proposed_status and not l.status)
            for line in targets:
                line.status = line.proposed_status
            rec.message_post(body=_("제안값 일괄 확정: %(n)s건 반영 (기존 수기판정 보존)")
                             % {"n": len(targets)})
        return True

    def action_view_weak_lines(self):
        """보강 필요 항목(제안 또는 확정이 보완 이하)만 조회."""
        self.ensure_one()
        weak = ("supplement", "partial_poor", "many_poor", "poor")
        return {
            "type": "ir.actions.act_window",
            "name": _("보강 필요 항목: %s") % self.name,
            "res_model": "sq.evaluation.line",
            "view_mode": "list,form",
            "domain": ["&", ("evaluation_id", "=", self.id),
                       "|", ("proposed_status", "in", weak), ("status", "in", weak)],
        }

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
    # ── 증빙 기반 자동채점 (제안 ≠ 확정 분리 — 명세 3-1) ──
    proposed_status = fields.Selection(STATUS_SELECTION, string="제안 이행상태", readonly=True)
    proposed_ratio = fields.Float(string="제안 배율", compute="_compute_proposed_ratio", digits=(3, 2))
    proposed_reason = fields.Char(string="제안 근거", readonly=True)
    auto_scored = fields.Boolean(string="자동채점됨", readonly=True)
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

    @api.depends("proposed_status")
    def _compute_proposed_ratio(self):
        for rec in self:
            rec.proposed_ratio = STATUS_RATIO.get(rec.proposed_status, 0.0)

    # ── 증빙 기반 자동채점 규칙 (명세 3-3, 임계값은 시뮬 실측으로 검증) ──
    def _auto_propose(self):
        """(proposed_status, reason) 반환. 수기 항목은 (False, 사유)."""
        self.ensure_one()
        src = self.evidence_source
        model, label = self._evidence_target()
        if not model:
            return False, _("수기 증빙 항목(자동 대상 아님)")
        M = self.env[model]
        domain = self._evidence_domain()
        n = M.search_count(domain)

        if src in ("iqc", "process_inspection"):
            decided = M.search_count(domain + [("result", "in", ("pass", "conditional", "fail"))])
            if not decided:
                return "poor", _("판정된 검사 0건")
            passed = M.search_count(domain + [("result", "in", ("pass", "conditional"))])
            rate = passed / decided * 100.0
            st = "excellent" if rate >= 99 else "good" if rate >= 95 else "supplement"
            return st, _("합격률 %(r).1f%% (%(p)s/%(d)s건)") % {"r": rate, "p": passed, "d": decided}

        if src == "spc":
            recs = M.search(domain + [("cpk", ">", 0)])
            if not recs:
                return "poor", _("Cpk 산출 SPC 0건")
            avg = sum(recs.mapped("cpk")) / len(recs)
            st = ("excellent" if avg >= 1.67 else "good" if avg >= 1.33
                  else "supplement" if avg >= 1.0 else "many_poor")
            return st, _("평균 Cpk %(c).2f (%(n)s건)") % {"c": avg, "n": len(recs)}

        if src == "msa":
            recs = M.search(domain + [("pct_grr", ">", 0)])
            if not recs:
                return "poor", _("GRR 산출 MSA 0건")
            worst = max(recs.mapped("pct_grr"))
            st = "excellent" if worst < 10 else "good" if worst <= 30 else "supplement"
            return st, _("최대 %%GRR %(g).1f%% (%(n)s건)") % {"g": worst, "n": len(recs)}

        if src == "calibration":
            if not n:
                return "poor", _("교정기록 0건")
            overdue = M.search_count(domain + [("next_due_date", "<", fields.Date.today())])
            if overdue:
                return "partial_poor", _("차기 교정일 초과 %(o)s건 / 총 %(n)s건") % {"o": overdue, "n": n}
            return "excellent", _("교정 %(n)s건, 기한 초과 없음") % {"n": n}

        if src in ("nc", "corrective_action"):
            if not n:
                return "supplement", _("기록 0건 — 프로세스 운영 실증 불가")
            closed = M.search_count(domain + [("state", "in", ("closed", "verified"))])
            rate = closed / n * 100.0
            st = "excellent" if rate >= 90 else "good" if rate >= 70 else "supplement"
            return st, _("종결율 %(r).0f%% (%(c)s/%(n)s건)") % {"r": rate, "c": closed, "n": n}

        if src in ("ppap", "apqp", "fmea", "control_plan"):
            approved = 0
            if "state" in M._fields:
                approved = M.search_count(domain + [
                    ("state", "in", ("approved", "closed", "completed", "customer_approved"))])
            if approved:
                return "excellent", _("%(l)s 승인/완료 %(a)s건") % {"l": label, "a": approved}
            if n:
                return "supplement", _("%(l)s %(n)s건 (승인/완료 없음)") % {"l": label, "n": n}
            return "poor", _("%(l)s 0건") % {"l": label}

        if src == "field_record":
            if not n:
                return "poor", _("점검기록 0건")
            recs = M.search(domain)
            conform = len(recs.filtered(lambda r: r.result == "conform"))
            rate = conform / len(recs) * 100.0
            st = "excellent" if rate >= 95 else "good" if rate >= 80 else "supplement"
            return st, _("점검 적합률 %(r).0f%% (%(c)s/%(n)s건)") % {"r": rate, "c": conform, "n": len(recs)}

        # 건수형 기본 (traceability/document/training/equipment/mold/jig/environment/audit/...)
        if n:
            return "good", _("%(l)s %(n)s건 확보") % {"l": label or model, "n": n}
        return "poor", _("%(l)s 기록 0건") % {"l": label or model}
