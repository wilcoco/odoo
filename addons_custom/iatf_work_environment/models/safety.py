from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# 위험성 = 가능성(빈도) × 중대성(강도). 3×3 매트릭스.
# 숫자는 라벨이 아니라 계산에 쓰므로 Selection 값을 문자열 숫자로 둔다.
LIKELIHOOD = [("1", "낮음 (1)"), ("2", "보통 (2)"), ("3", "높음 (3)")]
SEVERITY = [("1", "경미 (1)"), ("2", "중대 (2)"), ("3", "치명 (3)")]


class IatfSafetyAssessment(models.Model):
    """위험성평가 대장 — SQ 사출 6_1.

    IATF 리스크 등록부(`iatf.risk.register`) 와 다른 원장이다.
    저쪽은 사업·공정 리스크와 기회(§6.1)를 다루고, 이쪽은 **작업별 유해위험요인**을
    가능성×중대성으로 평가하고 감소대책의 이행까지 추적한다. 평가 주기·개선 전후
    위험성 비교가 필요해 구조가 다르다. 섞으면 어느 쪽 증빙도 못 된다.
    """

    _name = "iatf.safety.assessment"
    _description = "위험성평가 (SQ 6_1)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "assess_date desc, id desc"

    name = fields.Char(string="평가 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    title = fields.Char(string="평가 대상 작업", required=True, tracking=True,
                        help="예: 사출기 금형 교환 작업, 분쇄기 투입 작업")
    assess_type = fields.Selection(
        [("initial", "최초"), ("regular", "정기"), ("occasional", "수시")],
        string="평가 구분", required=True, default="initial", tracking=True,
        help="수시 = 설비 신규 도입·공정 변경·사고 발생 시")
    assess_date = fields.Date(string="평가일", required=True,
                              default=fields.Date.context_today, tracking=True)
    work_area_id = fields.Many2one("iatf.work.area", string="작업 구역")
    equipment_id = fields.Many2one("iatf.equipment", string="관련 설비", ondelete="set null")
    department_id = fields.Many2one("hr.department", string="관리 부서")
    leader_id = fields.Many2one("res.users", string="평가 책임자",
                                default=lambda self: self.env.user, tracking=True)
    participant_ids = fields.Many2many("res.users", string="평가 참여자",
                                       help="위험성평가는 근로자 참여가 요건이다.")
    trigger = fields.Char(string="수시평가 사유")

    line_ids = fields.One2many("iatf.safety.assessment.line", "assessment_id",
                               string="유해위험요인")
    line_count = fields.Integer(string="요인 수", compute="_compute_stats", store=True)
    unacceptable_count = fields.Integer(string="허용불가 요인 수", compute="_compute_stats",
                                        store=True)
    open_action_count = fields.Integer(string="미완료 대책 수", compute="_compute_stats",
                                       store=True)
    max_risk = fields.Integer(string="최고 위험성", compute="_compute_stats", store=True)

    state = fields.Selection(
        [("draft", "작성 중"), ("done", "평가 완료"), ("cancelled", "취소")],
        string="상태", default="draft", required=True, tracking=True)
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("line_ids.risk_score", "line_ids.acceptable", "line_ids.action_state")
    def _compute_stats(self):
        for rec in self:
            lines = rec.line_ids
            rec.line_count = len(lines)
            rec.unacceptable_count = len(lines.filtered(lambda l: not l.acceptable))
            rec.open_action_count = len(
                lines.filtered(lambda l: l.measure and l.action_state != "done"))
            rec.max_risk = max(lines.mapped("risk_score")) if lines else 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "iatf.safety.assessment") or _("New")
        return super().create(vals_list)

    @api.constrains("assess_date")
    def _check_date_not_future(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.assess_date and rec.assess_date > today:
                raise ValidationError(_("평가일을 미래로 지정할 수 없습니다."))

    def _missing_for_done(self):
        """완료에 부족한 것을 돌려준다. 버튼과 백스톱이 같은 규칙을 쓰게 한다."""
        self.ensure_one()
        if not self.line_ids:
            return _("유해위험요인이 하나도 없습니다. 평가 내용을 입력한 뒤 완료하십시오.")
        missing = self.line_ids.filtered(lambda l: not l.acceptable and not l.measure)
        if missing:
            return _("허용 불가로 판정된 요인에 감소대책이 없습니다: %s",
                     ", ".join(missing.mapped("hazard")))
        return False

    @api.constrains("state", "line_ids")
    def _check_done_is_complete(self):
        """완료 상태의 백스톱.

        `action_done` 은 버튼 경로에만 걸린다. `write({'state': 'done'})` 이나
        완료 후 라인을 지우는 경로로 우회하면 '평가 완료' 건수만 남고 내용이 빈다.
        """
        for rec in self:
            if rec.state != "done":
                continue
            problem = rec._missing_for_done()
            if problem:
                raise ValidationError(_("%(name)s: %(problem)s",
                                        name=rec.name, problem=problem))

    def action_done(self):
        """평가 완료. 유해위험요인이 하나도 없는 평가는 완료할 수 없다.

        '위험요인 없음' 을 완료로 남기면 평가를 한 것처럼 보이지만 실제로는
        아무것도 평가하지 않은 기록이다. 빈 점검표와 같은 문제다.
        """
        for rec in self:
            problem = rec._missing_for_done()
            if problem:
                raise UserError(_("%(name)s: %(problem)s",
                                  name=rec.name, problem=problem))
            rec.state = "done"

    def action_draft(self):
        self.write({"state": "draft"})

    def action_cancel(self):
        self.write({"state": "cancelled"})


class IatfSafetyAssessmentLine(models.Model):
    _name = "iatf.safety.assessment.line"
    _description = "유해위험요인 / 감소대책"
    _order = "sequence, id"

    assessment_id = fields.Many2one("iatf.safety.assessment", string="위험성평가",
                                    required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    hazard = fields.Char(string="유해·위험요인", required=True,
                         help="예: 금형 낙하, 협착, 분쇄기 칼날 접촉, 유기용제 흡입")
    hazard_type = fields.Selection(
        [("mechanical", "기계적"), ("electrical", "전기적"), ("chemical", "화학적"),
         ("ergonomic", "인간공학적"), ("fire", "화재·폭발"), ("fall", "추락·전도"),
         ("other", "기타")],
        string="분류", default="mechanical")
    current_control = fields.Char(string="현재 안전보건조치")

    likelihood = fields.Selection(LIKELIHOOD, string="가능성", required=True, default="2")
    severity = fields.Selection(SEVERITY, string="중대성", required=True, default="2")
    risk_score = fields.Integer(string="위험성", compute="_compute_risk", store=True)
    risk_level = fields.Selection(
        [("low", "낮음"), ("medium", "보통"), ("high", "높음")],
        string="위험성 등급", compute="_compute_risk", store=True)
    acceptable = fields.Boolean(string="허용 가능", compute="_compute_risk", store=True,
                                help="위험성 4 이상은 허용 불가로 본다. 감소대책이 있어야 평가를 완료할 수 있다.")

    measure = fields.Char(string="감소대책")
    responsible_id = fields.Many2one("res.users", string="조치 담당")
    due_date = fields.Date(string="조치 기한")
    action_state = fields.Selection(
        [("todo", "미착수"), ("doing", "진행 중"), ("done", "완료")],
        string="조치 상태", default="todo")
    done_date = fields.Date(string="조치 완료일")

    # 개선 후 재평가
    after_likelihood = fields.Selection(LIKELIHOOD, string="개선 후 가능성")
    after_severity = fields.Selection(SEVERITY, string="개선 후 중대성")
    after_risk_score = fields.Integer(string="개선 후 위험성", compute="_compute_after_risk",
                                      store=True)

    @api.depends("likelihood", "severity")
    def _compute_risk(self):
        for rec in self:
            score = int(rec.likelihood or 0) * int(rec.severity or 0)
            rec.risk_score = score
            if score >= 6:
                rec.risk_level = "high"
            elif score >= 4:
                rec.risk_level = "medium"
            else:
                rec.risk_level = "low"
            rec.acceptable = score < 4

    @api.depends("after_likelihood", "after_severity")
    def _compute_after_risk(self):
        for rec in self:
            # 둘 다 넣어야 재평가로 본다. 하나만 넣으면 0(미평가).
            if rec.after_likelihood and rec.after_severity:
                rec.after_risk_score = int(rec.after_likelihood) * int(rec.after_severity)
            else:
                rec.after_risk_score = 0

    @api.constrains("action_state", "done_date", "measure")
    def _check_action_done(self):
        """완료로 표시하려면 대책과 완료일이 있어야 한다."""
        for rec in self:
            if rec.action_state == "done":
                if not rec.measure:
                    raise ValidationError(_(
                        "'%s' 의 감소대책이 비어 있는데 조치 완료로 표시했습니다.", rec.hazard))
                if not rec.done_date:
                    raise ValidationError(_(
                        "'%s' 의 조치 완료일을 입력하십시오.", rec.hazard))

    @api.constrains("done_date")
    def _check_done_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.done_date and rec.done_date > today:
                raise ValidationError(_("조치 완료일을 미래로 지정할 수 없습니다."))

    def unlink(self):
        """라인을 지운 뒤 부모를 다시 검사한다.

        자식 삭제는 부모의 `@api.constrains("line_ids")` 를 트리거하지 않는다.
        그래서 완료된 평가의 라인을 전부 지우면 '평가 완료' 건수만 남고 내용이
        빈 기록이 된다. 삭제 후 직접 다시 본다.
        """
        parents = self.assessment_id
        res = super().unlink()
        parents.exists()._check_done_is_complete()
        return res

    @api.constrains("acceptable", "measure", "assessment_id")
    def _check_parent_still_complete(self):
        """완료된 평가의 라인을 나중에 손대는 경로를 막는다.

        부모의 `@api.constrains` 는 점 표기를 지원하지 않아 라인 필드 변경으로는
        돌지 않는다. 그래서 라인 쪽에서 부모를 다시 검사한다.
        """
        for rec in self:
            parent = rec.assessment_id
            if parent.state == "done":
                problem = parent._missing_for_done()
                if problem:
                    raise ValidationError(_("%(name)s: %(problem)s",
                                            name=parent.name, problem=problem))


class IatfSafetyIncident(models.Model):
    """아차사고 / 사고 이력 — SQ 사출 6_1.

    아차사고(near miss)를 사고와 **같은 원장**에 둔다. 아차사고를 따로 관리하면
    "사고 0건" 이라는 숫자만 남고 예방 활동의 증빙이 사라진다. 평가에서 보는 것은
    사고가 없다는 사실이 아니라 **위험을 발견하고 조치한 이력**이다.
    """

    _name = "iatf.safety.incident"
    _description = "아차사고 / 사고 이력 (SQ 6_1)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "occurred_at desc, id desc"

    name = fields.Char(string="발생 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    title = fields.Char(string="제목", required=True, tracking=True)
    incident_type = fields.Selection(
        [("near_miss", "아차사고"), ("first_aid", "응급처치"), ("lost_time", "휴업재해"),
         ("property", "물적사고"), ("fire", "화재"), ("other", "기타")],
        string="구분", required=True, default="near_miss", tracking=True)
    occurred_at = fields.Datetime(string="발생 일시", required=True,
                                  default=fields.Datetime.now, tracking=True)
    work_area_id = fields.Many2one("iatf.work.area", string="발생 구역")
    equipment_id = fields.Many2one("iatf.equipment", string="관련 설비", ondelete="set null")
    location_name = fields.Char(string="발생 장소")
    reporter_id = fields.Many2one("res.users", string="보고자",
                                  default=lambda self: self.env.user, tracking=True)
    involved_employee_ids = fields.Many2many("hr.employee", string="관련자")
    lost_days = fields.Integer(string="휴업 일수")

    description = fields.Text(string="발생 경위", required=True)
    cause = fields.Text(string="원인 분석")
    immediate_action = fields.Text(string="즉시 조치")
    countermeasure = fields.Text(string="재발방지 대책")
    responsible_id = fields.Many2one("res.users", string="대책 담당")
    due_date = fields.Date(string="대책 기한")
    done_date = fields.Date(string="대책 완료일")

    assessment_id = fields.Many2one(
        "iatf.safety.assessment", string="관련 위험성평가", ondelete="set null",
        help="사고 발생 시 해당 작업의 위험성평가를 수시로 다시 해야 한다. 그 평가를 연결한다.")

    state = fields.Selection(
        [("reported", "접수"), ("analyzing", "원인 분석"), ("action", "대책 이행"),
         ("closed", "종결"), ("cancelled", "취소")],
        string="상태", default="reported", required=True, tracking=True)
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "iatf.safety.incident") or _("New")
        return super().create(vals_list)

    @api.constrains("occurred_at")
    def _check_occurred_not_future(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.occurred_at and rec.occurred_at > now:
                raise ValidationError(_("발생 일시를 미래로 지정할 수 없습니다."))

    @api.constrains("done_date")
    def _check_done_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.done_date and rec.done_date > today:
                raise ValidationError(_("대책 완료일을 미래로 지정할 수 없습니다."))

    def action_analyze(self):
        self.write({"state": "analyzing"})

    def action_start_action(self):
        for rec in self:
            if not rec.cause:
                raise UserError(_("원인 분석을 입력한 뒤 대책 이행으로 넘기십시오. (%s)", rec.name))
            rec.state = "action"

    def _missing_for_close(self):
        self.ensure_one()
        missing = []
        if not self.cause:
            missing.append(_("원인 분석"))
        if not self.countermeasure:
            missing.append(_("재발방지 대책"))
        if not self.done_date:
            missing.append(_("대책 완료일"))
        return missing

    @api.constrains("state", "cause", "countermeasure", "done_date")
    def _check_closed_is_complete(self):
        """종결 상태의 백스톱. `write({'state': 'closed'})` 우회를 막는다.

        종결 후에 원인·대책을 지우는 경로도 함께 막힌다. 증빙을 남긴 뒤
        내용만 비우면 건수 집계가 사실과 달라진다.
        """
        for rec in self:
            if rec.state != "closed":
                continue
            missing = rec._missing_for_close()
            if missing:
                raise ValidationError(_(
                    "%(fields)s 이(가) 비어 있어 종결 상태로 둘 수 없습니다. (%(name)s)",
                    fields=", ".join(missing), name=rec.name))

    def action_close(self):
        """종결. 원인·대책·완료일 없이 닫을 수 없다.

        여기를 열어 두면 '접수만 하고 종결' 이 실적으로 집계된다.
        평가에서 보는 것은 접수 건수가 아니라 조치가 끝났다는 증빙이다.
        """
        for rec in self:
            missing = rec._missing_for_close()
            if missing:
                raise UserError(_(
                    "%(fields)s 이(가) 비어 있어 종결할 수 없습니다. (%(name)s)",
                    fields=", ".join(missing), name=rec.name))
            rec.state = "closed"

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset(self):
        self.write({"state": "reported"})
