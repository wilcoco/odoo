from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class IatfMoldCheck(models.Model):
    """금형 일상/정기 점검 — SQ 4_1.

    설비 일상점검(`iatf.daily.check`) 의 헤더+라인 구조를 따르되, 두 가지를 바꿨다.

    1. **라인이 비어 있으면 '양호' 가 아니라 '미완료'** 다. 설비 쪽은 라인이 하나도
       없어도 종합판정이 '양호' 로 계산된다 — 아무것도 점검하지 않은 빈 점검표가
       양호 실적으로 집계된다는 뜻이다. 크리아 4_1 감점 사유가 "점검표 작성 일부
       누락" 이었으므로 그 결함을 복사해 오면 안 된다.
    2. **완료(done) 건만 실적으로 센다.** 작성 중인 점검표는 이행실적이 아니다.
       세척(1-3)·시사출(1-5) 과 같은 규칙이다.
    """

    _name = "iatf.mold.check"
    _description = "금형 일상/정기 점검 (SQ 4_1)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "check_date desc, id desc"

    name = fields.Char(
        string="점검 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    mold_id = fields.Many2one(
        "iatf.mold", string="금형", required=True, index=True, tracking=True,
        # 점검 기록은 심사 증빙이다. 금형 삭제로 조용히 사라지면 "그 기간에
        # 점검을 했는가" 를 아무도 답할 수 없다. 금형은 폐기(disposed) 로 둔다.
        ondelete="restrict",
    )
    check_type = fields.Selection(
        [("daily", "일상"), ("periodic", "정기")],
        string="점검 구분", required=True, default="daily", tracking=True,
    )
    check_date = fields.Date(
        string="점검일", required=True, default=fields.Date.context_today, tracking=True,
    )
    shift = fields.Selection(
        [("day", "주간"), ("evening", "야간"), ("night", "심야")],
        string="근무조", default="day",
    )
    checker_id = fields.Many2one(
        "res.users", string="점검자", default=lambda self: self.env.user, tracking=True,
    )
    production_id = fields.Many2one(
        "mrp.production", string="관련 생산지시",
        help="이 점검이 어느 생산과 묶인 점검인지. 비워둘 수 있다.",
    )

    line_ids = fields.One2many("iatf.mold.check.line", "check_id", string="점검 항목")

    overall_result = fields.Selection(
        [("ok", "양호"), ("issue", "이상 있음"), ("pending", "미완료")],
        string="종합 판정", compute="_compute_overall", store=True,
        help="항목이 없거나 판정이 비어 있는 항목이 남아 있으면 '미완료'. "
             "빈 점검표가 '양호' 로 집계되지 않게 한다.",
    )
    ng_count = fields.Integer(string="이상 항목 수", compute="_compute_overall", store=True)

    state = fields.Selection(
        [("draft", "작성 중"), ("done", "완료"), ("cancelled", "취소")],
        string="상태", default="draft", required=True, tracking=True,
    )
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.mold.check") or _("New")
        return super().create(vals_list)

    def action_done(self):
        """완료 처리. 판정이 덜 된 점검표는 완료할 수 없다.

        여기를 열어두면 항목을 비운 채 완료로 넘긴 점검표가 실적으로 집계되고,
        그것이 정확히 크리아 4_1 의 "점검표 작성 일부 누락" 감점이다.
        """
        for rec in self:
            if rec.overall_result == "pending":
                raise UserError(_(
                    "점검 항목이 없거나 판정이 비어 있는 항목이 있습니다. "
                    "모든 항목의 결과를 기입한 뒤 완료하십시오. (%s)", rec.name,
                ))
            rec.state = "done"
            if rec.ng_count:
                rec.message_post(body=_(
                    "이상 항목 %s 건이 발견되었습니다. 조치 결과를 보전/수리 이력에 남기십시오.",
                    rec.ng_count,
                ))

    def action_draft(self):
        self.write({"state": "draft"})

    def action_cancel(self):
        self.write({"state": "cancelled"})


class IatfMoldCheckLine(models.Model):
    """점검 항목 한 줄.

    항목은 두 종류다.
    - **정량 항목**: 상·하한이 있고 측정값을 적는다 → 판정은 기준이 한다(사람이 못 고침)
    - **정성 항목**: 상·하한이 없다(예: "이물 부착 여부") → 사람이 양호/불량을 고른다
    """

    _name = "iatf.mold.check.line"
    _description = "금형 점검 항목"
    _order = "sequence, id"

    check_id = fields.Many2one(
        "iatf.mold.check", string="점검", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    item_name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="판정 기준", help="정성 항목의 기준 문구. 예: 이물 없을 것")

    spec_min = fields.Float(string="하한")
    spec_max = fields.Float(string="상한")
    value = fields.Float(string="측정값")
    uom_name = fields.Char(string="단위", help="예: ℃, bar, mm")

    result = fields.Selection(
        [("ok", "양호"), ("ng", "불량"), ("na", "해당없음")],
        string="결과", compute="_compute_result", store=True, readonly=False,
        help="상·하한이 있는 항목은 측정값에서 자동 판정되며 손으로 바꿀 수 없다. "
             "상·하한이 없는 정성 항목만 직접 고른다.",
    )
    remark = fields.Char(string="비고")

    def _has_spec(self):
        """상·하한 중 하나라도 있으면 정량 항목으로 본다.

        Float 은 '미설정' 과 '0' 을 구분하지 못한다. 0 을 기준으로 읽으면 기준을
        넣은 적 없는 항목이 전부 '0 초과 금지' 로 해석돼 없는 불량을 만들어낸다.
        """
        self.ensure_one()
        return bool(self.spec_min) or bool(self.spec_max)

    def judge_value(self):
        """측정값의 합·부. 'ok' | 'ng' | 'no_spec' | 'no_value'.

        측정값 0 은 '미기입' 으로 읽는다(`no_value`). 안 적은 칸을 하한 미달로
        읽으면 아직 점검하지 않은 항목이 전부 불량으로 찍힌다. 0 이 유효한
        측정값인 항목은 정량이 아니라 정성 항목으로 만들어 쓴다.
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
                # 기준이 있으면 사람이 아니라 기준이 판정한다. 상한 밖 측정값에
                # '양호' 를 적어 넣는 경로를 아예 만들지 않는다 — 그 경로가 곧
                # 허위기재(다수미흡 25%) 다.
                rec.result = judged
            else:
                # 정성 항목이거나 아직 측정값을 안 적었다 → 사람이 고른 값을 둔다.
                rec.result = rec.result

    @api.constrains("result", "value", "spec_min", "spec_max")
    def _check_result_matches_spec(self):
        """기준이 판정한 결과와 다른 결과를 저장하지 못하게 막는다.

        `_compute_result` 만으로는 부족하다. 편집 가능한 계산 필드라 의존 필드가
        바뀌지 않는 write(예: result 만 'ok' 로 덮어쓰기)에서는 재계산이 돌지
        않는다. 뷰의 readonly 도 서버에서 강제되지 않는다. 즉 여기서 막지 않으면
        상한 밖 측정값에 '양호' 를 적어 넣는 경로가 실제로 열려 있다 —
        그 경로가 곧 허위기재(SQ 다수미흡 25%)다.
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
                    judged=labels.get(judged), given=labels.get(rec.result) or _("미판정"),
                ))

    @api.constrains("spec_min", "spec_max")
    def _check_spec_range(self):
        for rec in self:
            if rec.spec_min and rec.spec_max and rec.spec_min > rec.spec_max:
                raise ValidationError(_(
                    "'%(item)s' 의 하한(%(low)s) 이 상한(%(high)s) 보다 큽니다.",
                    item=rec.item_name, low=rec.spec_min, high=rec.spec_max,
                ))
