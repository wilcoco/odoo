from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# 주기 → 일수. 'event'(발생시) 는 주기가 없다 — 기한 판정을 하지 않는다.
# 'shift'(교대) 는 하루 여러 번이지만 기한 판정은 일 단위로만 한다.
CYCLE_DAYS = {
    "shift": 1,
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
}


class IatfCheckSheet(models.Model):
    """범용 점검 시트 — 무엇을 어떤 주기로 점검하는가 (관리기준).

    전동공구 토크, 통전검사 마스터, 바코드 마스터, 원소재 건조기 필터,
    분쇄기·배합기, 냉각수·작동유 온도, 소화기 — 대상만 다르고 구조가 같은
    점검들을 **모델 하나**로 덮는다. 대상별 전용 모듈을 만들지 않는다.

    금형(`iatf.mold.check`)·설비 일상점검(`iatf.daily.check`)·작업환경 5S
    (`iatf.environment.check`) 는 각자 고유 구조(주기가 마스터에 있음, 5S 5개
    점수 등)가 있어 여기로 흡수하지 않는다. 경계는 addons_custom/CLAUDE.md 참조.
    """

    _name = "iatf.check.sheet"
    _description = "범용 점검 시트 (점검 마스터)"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(string="점검 시트명", required=True, tracking=True)
    code = fields.Char(string="코드", copy=False)
    target_type = fields.Selection(
        [
            ("tool", "공구"),
            ("master", "검사 마스터"),
            ("facility", "설비/시설"),
            ("area", "구역"),
            ("etc", "기타"),
        ],
        string="대상 구분", required=True, default="facility", tracking=True,
    )

    # ── 대상 연결 (전부 선택) ──
    # 점검 대상이 설비 대장에 없는 경우가 많다(소화기·바코드리더·전동공구).
    # 그래서 어느 것도 필수로 두지 않고, 자유 기재 위치를 함께 둔다.
    equipment_id = fields.Many2one("iatf.equipment", string="설비", ondelete="set null")
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장", ondelete="set null")
    work_area_id = fields.Many2one("iatf.work.area", string="작업 구역", ondelete="set null")
    location_name = fields.Char(string="설치 위치", help="설비 대장에 없는 대상의 위치를 적는다. 예: 창고 A동 출입구 소화기 3호")

    # ── 주기 ──
    cycle = fields.Selection(
        [
            ("shift", "교대"),
            ("daily", "일"),
            ("weekly", "주"),
            ("monthly", "월"),
            ("quarterly", "분기"),
            ("yearly", "연"),
            ("event", "발생시"),
        ],
        string="점검 주기", required=True, default="daily", tracking=True,
    )
    start_date = fields.Date(
        string="운용 시작일", default=fields.Date.context_today, tracking=True,
        help="이 날부터 주기를 센다. 한 번도 점검하지 않은 시트도 시작일 + 주기가 지나면 "
             "미실시로 잡힌다. 비우면 기한 판정을 하지 않는다.",
    )
    responsible_id = fields.Many2one("res.users", string="점검 책임자",
                                     default=lambda self: self.env.user, tracking=True)
    department_id = fields.Many2one("hr.department", string="관리 부서")

    item_ids = fields.One2many("iatf.check.sheet.item", "sheet_id", string="점검 항목")
    item_count = fields.Integer(string="항목 수", compute="_compute_item_count")
    record_ids = fields.One2many("iatf.check.record", "sheet_id", string="점검 실적")
    record_count = fields.Integer(string="실적 건수", compute="_compute_record_count")

    last_record_date = fields.Date(
        string="최근 점검일", compute="_compute_due", store=True,
        help="완료(done) 된 점검만 센다. 작성 중인 점검표는 실적이 아니다.",
    )
    next_due = fields.Date(string="차기 점검 예정", compute="_compute_due", store=True)
    # 오늘 날짜에 의존하므로 저장하지 않는다. 저장하면 값이 굳어 기한이 지나도 '정상'으로 보인다.
    is_overdue = fields.Boolean(string="미실시(기한 경과)", compute="_compute_overdue",
                                search="_search_is_overdue")

    active = fields.Boolean(default=True)
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        ("uniq_check_sheet_code", "unique(code)", "점검 시트 코드가 중복됩니다."),
    ]

    @api.depends("item_ids")
    def _compute_item_count(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)

    @api.depends("record_ids")
    def _compute_record_count(self):
        for rec in self:
            rec.record_count = len(rec.record_ids)

    @api.depends("cycle", "start_date", "record_ids.check_date", "record_ids.state")
    def _compute_due(self):
        for rec in self:
            done = rec.record_ids.filtered(lambda r: r.state == "done" and r.check_date)
            last = max(done.mapped("check_date")) if done else False
            rec.last_record_date = last
            days = CYCLE_DAYS.get(rec.cycle)
            # 한 번도 점검하지 않았으면 운용 시작일부터 센다. 이게 없으면 시트를
            # 만들어 놓고 한 번도 실행하지 않은 대상이 미실시 목록에 영영 안 뜬다.
            base = last or rec.start_date
            rec.next_due = fields.Date.add(base, days=days) if (days and base) else False

    @api.depends("next_due")
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.next_due) and rec.next_due < today

    def _search_is_overdue(self, operator, value):
        """'예정일이 오늘보다 이전' 을 저장 필드 기준 SQL 도메인으로 바꿔 넘긴다."""
        if operator not in ("=", "!="):
            raise ValidationError(_("'미실시(기한 경과)' 는 = 또는 != 로만 검색할 수 있습니다."))
        today = fields.Date.context_today(self)
        want_overdue = (operator == "=") == bool(value)
        if want_overdue:
            return [("next_due", "!=", False), ("next_due", "<", today)]
        return ["|", ("next_due", "=", False), ("next_due", ">=", today)]

    def _prepare_record_lines(self):
        """실적 라인을 시트 항목에서 만든다.

        기준(항목명·판정기준·상하한)을 **복사**해 둔다. 나중에 시트 기준이 바뀌어도
        과거 실적은 그때 적용된 기준을 그대로 보존해야 심사 증빙이 된다.
        """
        self.ensure_one()
        return [
            (0, 0, {
                "item_id": item.id,
                "sequence": item.sequence,
                "item_name": item.name,
                "standard": item.standard,
                "check_method": item.check_method,
                "spec_min": item.spec_min,
                "spec_max": item.spec_max,
                "uom_name": item.uom_name,
            })
            for item in self.item_ids
        ]

    def action_view_records(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("점검 실적"),
            "res_model": "iatf.check.record",
            "view_mode": "list,form",
            "domain": [("sheet_id", "=", self.id)],
            "context": {"default_sheet_id": self.id},
        }

    def action_new_record(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("점검 실적"),
            "res_model": "iatf.check.record",
            "view_mode": "form",
            "context": {"default_sheet_id": self.id},
        }


class IatfCheckSheetItem(models.Model):
    _name = "iatf.check.sheet.item"
    _description = "점검 항목 (기준)"
    _order = "sequence, id"

    sheet_id = fields.Many2one("iatf.check.sheet", string="점검 시트", required=True,
                               ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="판정 기준", help="정성 항목은 여기에 기준을 글로 적는다. 예: 균열·마모 없을 것")
    check_method = fields.Selection(
        [("visual", "육안"), ("measure", "측정"), ("function", "작동"), ("other", "기타")],
        string="점검 방법", default="visual",
    )
    spec_min = fields.Float(string="하한")
    spec_max = fields.Float(string="상한")
    uom_name = fields.Char(string="단위")
    active = fields.Boolean(default=True)

    @api.constrains("spec_min", "spec_max")
    def _check_spec_range(self):
        for rec in self:
            if rec.spec_min and rec.spec_max and rec.spec_min > rec.spec_max:
                raise ValidationError(_(
                    "'%(item)s' 의 하한(%(low)s) 이 상한(%(high)s) 보다 큽니다.",
                    item=rec.name, low=rec.spec_min, high=rec.spec_max))


class IatfCheckRecord(models.Model):
    """점검 실적 — 언제 누가 무엇을 점검했는가.

    `iatf.mold.check` 와 같은 규칙을 쓴다.
    1. 항목이 비었거나 판정이 덜 된 점검표는 '양호' 가 아니라 '미완료' 다.
    2. 완료(done) 건만 실적으로 센다.
    """

    _name = "iatf.check.record"
    _description = "점검 실적"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "check_date desc, id desc"

    name = fields.Char(string="점검 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    sheet_id = fields.Many2one("iatf.check.sheet", string="점검 시트", required=True,
                               index=True, tracking=True, ondelete="restrict")
    target_type = fields.Selection(related="sheet_id.target_type", string="대상 구분", store=True)
    cycle = fields.Selection(related="sheet_id.cycle", string="점검 주기", store=True)
    check_date = fields.Date(string="점검일", required=True,
                             default=fields.Date.context_today, tracking=True)
    shift = fields.Selection([("day", "주간"), ("evening", "야간"), ("night", "심야")],
                             string="근무조", default="day")
    checker_id = fields.Many2one("res.users", string="점검자",
                                 default=lambda self: self.env.user, tracking=True)
    line_ids = fields.One2many("iatf.check.record.line", "record_id", string="점검 항목")
    overall_result = fields.Selection(
        [("ok", "양호"), ("issue", "이상 있음"), ("pending", "미완료")],
        string="종합 판정", compute="_compute_overall", store=True)
    ng_count = fields.Integer(string="이상 항목 수", compute="_compute_overall", store=True)
    state = fields.Selection([("draft", "작성 중"), ("done", "완료"), ("cancelled", "취소")],
                             string="상태", default="draft", required=True, tracking=True)
    corrective_action = fields.Text(string="조치 내용")
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("line_ids.result")
    def _compute_overall(self):
        for rec in self:
            lines = rec.line_ids
            rec.ng_count = len(lines.filtered(lambda l: l.result == "ng"))
            if not lines or any(not l.result for l in lines):
                # 점검하지 않은 것과 이상 없는 것은 다른 사실이다.
                rec.overall_result = "pending"
            elif rec.ng_count:
                rec.overall_result = "issue"
            else:
                rec.overall_result = "ok"

    @api.constrains("check_date")
    def _check_date_not_future(self):
        """미래 날짜 점검은 실적이 아니다.

        차기 예정일이 최근 점검일에서 계산되므로, 미래 날짜로 기록하면 미실시
        목록에서 사라진다. 즉 '아직 하지 않은 점검' 을 이행한 것처럼 만들 수 있는
        경로다 — 막는다.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.check_date and rec.check_date > today:
                raise ValidationError(_(
                    "점검일(%(date)s)을 미래로 지정할 수 없습니다. 오늘은 %(today)s 입니다.",
                    date=rec.check_date, today=today))

    @api.onchange("sheet_id")
    def _onchange_sheet_id(self):
        # 시트를 바꾸면 항목을 전부 갈아끼운다. 남겨 두면 다른 시트의 항목이
        # 섞인 점검표가 만들어진다.
        if self.sheet_id:
            self.line_ids = [(5, 0, 0)] + self.sheet_id._prepare_record_lines()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.check.record") or _("New")
            # onchange 는 화면에서만 돈다. API·테스트·가져오기 경로에서도 같은
            # 결과가 나오도록 서버에서 한 번 더 채운다.
            if vals.get("sheet_id") and not vals.get("line_ids"):
                sheet = self.env["iatf.check.sheet"].browse(vals["sheet_id"])
                vals["line_ids"] = sheet._prepare_record_lines()
        return super().create(vals_list)

    def action_done(self):
        """완료 처리. 판정이 덜 된 점검표는 완료할 수 없다."""
        for rec in self:
            if rec.overall_result == "pending":
                raise UserError(_(
                    "점검 항목이 없거나 판정이 비어 있는 항목이 있습니다. "
                    "모든 항목의 결과를 기입한 뒤 완료하십시오. (%s)", rec.name))
            rec.state = "done"
            if rec.ng_count:
                rec.message_post(body=_(
                    "이상 항목 %s 건이 발견되었습니다. 조치 내용을 남기십시오.", rec.ng_count))

    def action_draft(self):
        self.write({"state": "draft"})

    def action_cancel(self):
        self.write({"state": "cancelled"})


class IatfCheckRecordLine(models.Model):
    _name = "iatf.check.record.line"
    _description = "점검 실적 항목"
    _order = "sequence, id"

    record_id = fields.Many2one("iatf.check.record", string="점검 실적", required=True,
                                ondelete="cascade", index=True)
    item_id = fields.Many2one("iatf.check.sheet.item", string="기준 항목", ondelete="set null")
    sequence = fields.Integer(default=10)
    # 기준을 복사해 둔다. 시트 기준이 바뀌어도 과거 실적의 판정 근거가 남아야 한다.
    item_name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="판정 기준")
    check_method = fields.Selection(
        [("visual", "육안"), ("measure", "측정"), ("function", "작동"), ("other", "기타")],
        string="점검 방법")
    spec_min = fields.Float(string="하한")
    spec_max = fields.Float(string="상한")
    value = fields.Float(string="측정값")
    uom_name = fields.Char(string="단위")
    result = fields.Selection([("ok", "양호"), ("ng", "불량"), ("na", "해당없음")],
                              string="결과", compute="_compute_result", store=True, readonly=False)
    remark = fields.Char(string="비고")

    def _has_spec(self):
        self.ensure_one()
        return bool(self.spec_min) or bool(self.spec_max)

    def judge_value(self):
        """'ok' | 'ng' | 'no_spec' | 'no_value'.

        기준값 0 은 '미설정' 으로 읽는다. 측정값 0 도 '미기입' 으로 읽는다.
        0 을 기준·측정값으로 읽으면 기준을 넣은 적 없는 항목이 전부 부적합으로
        찍혀 없는 결함을 만들어낸다.
        """
        self.ensure_one()
        if not self._has_spec():
            return "no_spec"
        if not self.value:
            return "no_value"
        if self.spec_min and self.value < self.spec_min:
            return "ng"
        if self.spec_max and self.value > self.spec_max:
            return "ng"
        return "ok"

    @api.depends("value", "spec_min", "spec_max")
    def _compute_result(self):
        for rec in self:
            judged = rec.judge_value()
            if judged in ("ok", "ng"):
                rec.result = judged
            else:
                # 정성 항목·미기입은 사람이 고른다. 계산으로 덮지 않는다.
                rec.result = rec.result

    @api.constrains("result", "value", "spec_min", "spec_max")
    def _check_result_matches_spec(self):
        """기준이 판정한 결과와 다른 결과를 저장하지 못하게 막는다.

        `_compute_result` 만으로는 부족하다. 편집 가능한 계산 필드라 의존 필드가
        바뀌지 않는 write(예: result 만 'ok' 로 덮어쓰기)에서는 재계산이 돌지
        않고, 뷰의 readonly 도 서버에서 강제되지 않는다. 즉 여기서 막지 않으면
        상한 밖 측정값에 '양호' 를 적어 넣는 경로가 실제로 열려 있다 —
        그 경로가 곧 허위기재(SQ 다수미흡 25%)다.

        같은 규칙이 `iatf.mold.check.line._check_result_matches_spec` 에도 있다.
        둘 중 하나만 고치면 구멍이 생긴다. 하나로 합치는 작업은 PR #31 병합 후.
        """
        labels = dict(self._fields["result"].selection)
        for rec in self:
            judged = rec.judge_value()
            if judged in ("ok", "ng") and rec.result != judged:
                raise ValidationError(_(
                    "'%(item)s' 의 측정값 %(value)s 는 기준(%(low)s ~ %(high)s)상 "
                    "'%(judged)s' 입니다. '%(given)s' 으로 저장할 수 없습니다.",
                    item=rec.item_name, value=rec.value,
                    low=rec.spec_min or "-", high=rec.spec_max or "-",
                    judged=labels.get(judged), given=labels.get(rec.result) or _("미판정")))

    @api.constrains("spec_min", "spec_max")
    def _check_spec_range(self):
        for rec in self:
            if rec.spec_min and rec.spec_max and rec.spec_min > rec.spec_max:
                raise ValidationError(_(
                    "'%(item)s' 의 하한(%(low)s) 이 상한(%(high)s) 보다 큽니다.",
                    item=rec.item_name, low=rec.spec_min, high=rec.spec_max))
