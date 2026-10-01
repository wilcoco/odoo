import json

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
    snapshot_ids = fields.One2many(
        "iatf.mold.check.snapshot", "check_id", string="완료 스냅샷", readonly=True,
        help="완료로 넘어갈 때마다 그 시점의 측정값 전문을 한 벌 남긴다.")
    snapshot_count = fields.Integer(
        string="완료 차수", compute="_compute_snapshot_count", store=True)

    overall_result = fields.Selection(
        [("ok", "양호"), ("issue", "이상 있음"), ("pending", "미완료")],
        string="종합 판정", compute="_compute_overall", store=True,
        help="항목이 없거나 판정이 비어 있는 항목이 남아 있으면 '미완료'. "
             "빈 점검표가 '양호' 로 집계되지 않게 한다.",
    )
    ng_count = fields.Integer(string="이상 항목 수", compute="_compute_overall", store=True)
    na_count = fields.Integer(
        string="해당없음 항목 수", compute="_compute_overall", store=True,
        help="'해당없음' 으로 둔 항목 수. 양호와 섞이지 않게 따로 센다. 기준이 있는 "
             "수치 항목을 사유 없이 '해당없음' 으로 두면 종합 판정이 '미완료' 로 남는다.")

    # 한 번이라도 완료된 적이 있는가. `state` 만 보면 '작성 중' 으로 되돌린 뒤 지울 수 있다.
    # 완료 기록의 삭제를 막는 것은 그 순간의 상태가 아니라 **완료된 적이 있다는 사실**이다.
    # (아스트라 재검토 2026-09-10 ②)
    was_done = fields.Boolean(string="완료 이력", default=False, copy=False, readonly=True,
                              help="한 번이라도 완료 처리된 기록. 되돌려도 삭제할 수 없다.")
    state = fields.Selection(
        [("draft", "작성 중"), ("done", "완료"), ("cancelled", "취소")],
        string="상태", default="draft", required=True, tracking=True,
    )
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)


    @staticmethod
    def _na_is_substantiated(line):
        """'해당없음' 이 판정으로 인정되는가.

        기준(상·하한)이 있는 수치 항목을 재지 않고 `na` 로 두면 그것은 판정이 아니라
        **미실시**다. 그런데 종합 판정은 `na` 를 판정으로 세어 '양호' 를 냈다.
        (제3자 재검토 R04)

        아스트라 지침에 따라 **새 승인 정책을 만들지 않고**, 전면 금지도 하지 않는다.
        제외 사유(비고)가 적혀 있으면 판정으로 인정하고, 없으면 **미판정으로 표시**한다.
        기준이 없는 정성 항목의 `na` 는 원래부터 사유 없이도 정상이다.
        """
        if line.result != "na":
            return True
        if not line._has_spec():
            return True          # 정성 항목 — 기준이 없으니 '해당없음' 이 자연스럽다
        return bool((line.remark or "").strip())

    def _derive_overall(self):
        """항목에서 종합 판정을 도출한다. (판정, 이상 수, 해당없음 수)

        저장된 `overall_result` 를 믿을 수 없기 때문에 순수 함수로 뽑아 둔다.
        편집 가능한 계산 필드라 `write({'state':'done','overall_result':'ok'})` 처럼
        의존 필드가 바뀌지 않는 write 에서는 재계산이 돌지 않는다 — 즉 NG 항목이 든
        점검표를 '양호' 로 완료할 수 있었다. (아스트라 275 리뷰 Q275-02)
        """
        self.ensure_one()
        lines = self.line_ids
        ng = len(lines.filtered(lambda l: l.result == "ng"))
        na = len(lines.filtered(lambda l: l.result == "na"))
        unsubstantiated = lines.filtered(lambda l: not self._na_is_substantiated(l))
        if not lines or any(not l.result for l in lines) or unsubstantiated:
            # 점검하지 않은 것과 이상 없는 것은 다른 사실이다.
            return "pending", ng, na
        return ("issue" if ng else "ok"), ng, na

    @api.depends("line_ids.result", "line_ids.remark", "line_ids.spec_min", "line_ids.spec_max")
    def _compute_overall(self):
        for rec in self:
            rec.overall_result, rec.ng_count, rec.na_count = rec._derive_overall()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.mold.check") or _("New")
            if vals.get("state") == "done":
                # 처음부터 완료로 만든 기록도 완료 이력이다. 이걸 빼면
                # create(done) → write(draft) → unlink 로 완료 증빙이 지워진다.
                vals["was_done"] = True
        return super().create(vals_list)

    # 완료 뒤에도 고칠 수 있는 것. 그 외 필드는 완료 점검표에서 잠근다.
    _DONE_EDITABLE = {"state", "notes", "message_main_attachment_id"}

    def write(self, vals):
        """완료된 점검표의 사실(날짜·금형·항목)은 바꿀 수 없다.

        완료 실적은 '그때 그렇게 점검했다' 는 증빙이다. 완료 후 날짜를 옮기거나
        항목을 갈아끼우면 증빙이 아니라 편집물이 된다. 고쳐야 하면 '작성 중' 으로
        되돌리고(상태 변경은 chatter 에 남는다) 고친 뒤 다시 완료한다.
        (2026-09-10 제3자 검토 Q10)
        """
        if "was_done" in vals and not vals["was_done"]:
            # 완료 이력은 사실이지 설정값이 아니다. 이걸 지울 수 있으면 삭제 금지가
            # 통째로 무력해진다 — write({'was_done': False}) 뒤 unlink 가 통과한다.
            # (아스트라 독립재현 2026-09-10 ②)
            stamped = self.filtered("was_done")
            if stamped:
                raise ValidationError(_(
                    "완료 이력은 해제할 수 없습니다: %s",
                    ", ".join(stamped.mapped("name"))))
        locked = self.filtered(lambda r: r.state == "done")
        touched = set(vals) - self._DONE_EDITABLE
        if locked and touched and vals.get("state", "done") == "done":
            raise ValidationError(_(
                "완료된 점검표는 수정할 수 없습니다: %(names)s\n"
                "고치려면 먼저 '작성 중' 으로 되돌리십시오. (변경 항목: %(fields)s)",
                names=", ".join(locked.mapped("name")), fields=", ".join(sorted(touched))))
        becoming_done = self.filtered(lambda r: r.state != "done") if (
            vals.get("state") == "done") else self.browse()
        if vals.get("state") == "done":
            # 완료로 넘어간 사실을 같은 write 에 실어 남긴다. 되돌려도 지워지지 않는다.
            # 따로 write 를 부르면 재진입·잠금 검사와 얽힌다. (아스트라 재검토 ②)
            vals = dict(vals, was_done=True)
        res = super().write(vals)
        becoming_done._snapshot_on_done()
        return res

    def _snapshot_line_payload(self, line):
        """한 항목의 완료 시점 사실. 판정 근거가 되는 값만 담는다."""
        return {
            "순서": line.sequence,
            "항목": line.item_name,
            "기준": line.standard or "",
            "하한": line.spec_min,
            "상한": line.spec_max,
            "측정값": line.value,
            "단위": line.uom_name or "",
            "판정": line.result or "",
            "비고": line.remark or "",
        }

    def _snapshot_values(self):
        """완료 시점의 사실 전부. **서버가 원본에서 직접 만든다.**

        호출자가 준 값은 쓰지 않는다(부모 id 만 받는다). 종합 판정도 저장값이 아니라
        항목에서 다시 도출한다. 완료 당시의 대상·날짜·근무조·점검자·생산지시·회사도
        함께 얼려 둔다 — 되돌려 헤더를 고치고 재완료하면 그 사실을 복원할 수 없었다.
        (아스트라 275 리뷰 Q275-01·02·03)
        """
        self.ensure_one()
        labels = dict(self._fields["overall_result"].selection)
        derived, ng_count, _na = self._derive_overall()
        Snapshot = self.env["iatf.mold.check.snapshot"].sudo()
        return {
            "check_id": self.id,
            "revision": Snapshot.search_count([("check_id", "=", self.id)]) + 1,
            "done_at": fields.Datetime.now(),
            "done_by_id": self.env.user.id,
            "overall_result": labels.get(derived, derived),
            "ng_count": ng_count,
            "line_count": len(self.line_ids),
            # ── 완료 당시의 원본 식별 정보 (현재 값이 아니라 그때 값) ──
            "mold_id": self.mold_id.id,
            "mold_name": self.mold_id.display_name or "",
            "check_type": dict(self._fields["check_type"].selection).get(
                self.check_type, self.check_type or ""),
            "check_date": self.check_date,
            "shift": dict(self._fields["shift"].selection).get(self.shift, self.shift or ""),
            "checker_id": self.checker_id.id,
            "checker_name": self.checker_id.display_name or "",
            "production_name": self.production_id.display_name or "",
            "company_id": self.company_id.id,
            "company_name": self.company_id.display_name or "",
            "content": json.dumps(
                [self._snapshot_line_payload(l) for l in self.line_ids],
                ensure_ascii=False, indent=2),
        }

    def _snapshot_on_done(self):
        """완료로 넘어간 점검표의 측정값 전문을 한 벌 얼려 둔다."""
        if not self:
            return
        Snapshot = self.env["iatf.mold.check.snapshot"].sudo()
        Snapshot.with_context(**{Snapshot._SERVICE_KEY: True}).create(
            [{"check_id": rec.id} for rec in self])

    @api.depends("snapshot_ids")
    def _compute_snapshot_count(self):
        for rec in self:
            rec.snapshot_count = len(rec.snapshot_ids)

    @api.constrains("check_date")
    def _check_date_not_future(self):
        """미래 날짜 점검은 실적이 아니다.

        차기 예정일이 최근 점검일에서 계산되므로, 미래 날짜로 기록하면 미실시
        목록에서 사라진다 — '아직 하지 않은 점검' 을 이행한 것처럼 만드는 경로다.
        점검 시트에는 있던 규칙이 금형 점검엔 빠져 있었다. (제3자 검토 Q10)
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.check_date and rec.check_date > today:
                raise ValidationError(_(
                    "점검일(%(date)s)을 미래로 지정할 수 없습니다. 오늘은 %(today)s 입니다.",
                    date=rec.check_date, today=today))

    @api.constrains("state", "line_ids")
    def _check_done_is_complete(self):
        """완료 상태의 백스톱. `write({'state': 'done'})` 우회를 막는다.

        `action_done` 의 검사는 버튼 경로에만 걸린다. API·가져오기로 상태만 'done'
        으로 쓰면 판정이 비어 있는 점검표가 실적으로 집계된다. (제3자 검토 Q10)
        """
        for rec in self:
            if rec.state != "done":
                continue
            # 저장된 종합 판정을 믿지 않는다. `write({'state':'done','overall_result':'ok'})`
            # 처럼 둘을 같이 쓰면 재계산이 돌지 않아 저장된 값이 그대로 검사를 통과한다.
            # 사실의 근거는 라인이므로 라인에서 다시 센다. (제3자 재검토 R02)
            lines = rec.line_ids
            derived, _ng, _na = rec._derive_overall()
            if rec.overall_result != derived:
                # 저장된 종합 판정이 항목과 다르다 — 집계만 손으로 바꾼 완료다.
                # 그대로 두면 NG 가 든 점검표가 '양호' 실적으로 집계된다. (Q275-02)
                labels = dict(rec._fields["overall_result"].selection)
                raise ValidationError(_(
                    "종합 판정이 점검 항목과 맞지 않습니다: 저장값 '%(given)s' / "
                    "항목 기준 '%(derived)s'. 집계는 항목에서 정해집니다. (%(name)s)",
                    given=labels.get(rec.overall_result) or _("미지정"),
                    derived=labels.get(derived), name=rec.name))
            unsubstantiated = lines.filtered(lambda l: not self._na_is_substantiated(l))
            if not lines or any(not l.result for l in lines):
                raise ValidationError(_(
                    "판정이 비어 있는 항목이 있어 완료 상태로 둘 수 없습니다. (%s)", rec.name))
            if unsubstantiated:
                # 기준이 있는 항목을 사유 없이 '해당없음' 으로 둔 것 — 판정이 아니다. (R04)
                raise ValidationError(_(
                    "기준이 있는 항목을 사유 없이 '해당없음' 으로 둘 수 없습니다: %(items)s\n"
                    "측정했으면 값을 적고, 측정하지 않았다면 비고에 제외 사유를 남기십시오. (%(name)s)",
                    items=", ".join(unsubstantiated.mapped("item_name")), name=rec.name))

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


    def unlink(self):
        """완료된 점검표는 지울 수 없다 — 관리자도 마찬가지다.

        ACL 에서 관리자에게 unlink 를 준 것은 잘못 만든 초안을 치우라는 뜻이지
        완료된 증빙을 없애라는 뜻이 아니다. 완료 실적이 사라지면 미실시 목록에서도
        빠져 "점검한 적 없음" 과 구분되지 않는다. (제3자 재검토 R02)
        """
        locked = self.filtered(lambda r: r.state == "done" or r.was_done)
        if locked:
            raise ValidationError(_(
                "완료된 적이 있는 점검 기록은 삭제할 수 없습니다: %s\n"
                "잘못된 기록이면 '작성 중' 으로 되돌린 뒤 '취소' 로 남기십시오.",
                ", ".join(locked.mapped("name"))))
        return super().unlink()

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
            # 기준이 있는 항목에 측정값 없이 '양호/불량' 을 넣는 경로를 막는다.
            # 측정값 0(미기입)은 판정 불가이므로 결과도 비어 있어야 한다. 이걸
            # 열어 두면 상한이 있는 항목을 재지 않고 '양호' 로 채울 수 있다.
            # (제3자 검토 Q12 — 순수 함수 재현으로 실제 뚫림을 확인함)
            if judged == "no_value" and rec.result in ("ok", "ng"):
                raise ValidationError(_(
                    "'%(item)s' 은 기준(%(low)s ~ %(high)s)이 있는 항목입니다. 측정값 없이 "
                    "'%(given)s' 을 기록할 수 없습니다. 측정값을 적으면 자동 판정됩니다.",
                    item=rec.item_name, low=rec.spec_min or "-", high=rec.spec_max or "-",
                    given=labels.get(rec.result)))

    @api.model_create_multi
    def create(self, vals_list):
        """완료된 점검표에 항목을 새로 달 수 없다.

        부모 `write` 잠금은 `line_ids` 를 통한 경로만 막는다. 라인 모델에 직접
        `create({'check_id': 완료건})` 하면 그 경로를 타지 않아, 완료·양호였던 실적에
        미판정 라인이 붙어 '완료·미판정' 이 된다. (제3자 재검토 R01)
        """
        records = super().create(vals_list)
        locked = records.filtered(lambda l: l.check_id.state == "done")
        if locked:
            raise ValidationError(_(
                "완료된 점검표(%s)에는 항목을 추가할 수 없습니다. 먼저 '작성 중' 으로 되돌리십시오.",
                ", ".join(locked.mapped("check_id.name"))))
        return records

    def write(self, vals):
        """완료된 점검표의 항목은 고칠 수 없다. 부모의 잠금과 같은 이유다.

        완료된 적이 있는 점검표에서 항목을 **다른 점검표로 옮기는 것**도 막는다 —
        '작성 중' 으로 되돌린 뒤 라인을 빼내면 증빙이 사라진다. (아스트라 재검토 ②)
        """
        sources = self.check_id
        if "check_id" in vals:
            moving = self.filtered(lambda l: l.check_id.was_done or l.check_id.state == "done")
            if moving:
                raise ValidationError(_(
                    "완료된 적이 있는 점검표(%s)의 항목은 다른 점검표로 옮길 수 없습니다.",
                    ", ".join(moving.mapped("check_id.name"))))
            # 도착지도 봐야 한다. 미판정 라인을 완료된 점검표로 옮기면 그 점검표는
            # '완료' 인 채 '미완료' 판정이 되고, 부모 write 잠금은 이 경로를 지나지
            # 않는다. (아스트라 독립재현 ②)
            target = self.env["iatf.mold.check"].browse(vals["check_id"]).exists()
            if target and target.state == "done":
                raise ValidationError(_(
                    "완료된 점검표(%s)로 항목을 옮길 수 없습니다. 먼저 '작성 중' 으로 되돌리십시오.",
                    target.name))
        locked = self.filtered(lambda l: l.check_id.state == "done")
        if locked:
            raise ValidationError(_(
                "완료된 점검표(%s)의 항목은 수정할 수 없습니다. 먼저 '작성 중' 으로 되돌리십시오.",
                ", ".join(locked.mapped("check_id.name"))))
        res = super().write(vals)
        (sources | self.check_id).exists()._check_done_is_complete()
        return res

    def unlink(self):
        """완료된 점검표의 항목은 지울 수 없다. 지운 뒤에는 부모를 다시 검사한다.

        자식 삭제는 부모의 `@api.constrains("line_ids")` 를 트리거하지 않는다.
        """
        # 상태만 보면 '작성 중' 으로 되돌린 뒤 항목을 지워 증빙을 비울 수 있다.
        # 삭제를 막는 근거는 지금 상태가 아니라 **완료된 적이 있다는 사실**이다.
        # 값을 고치는 것은 되돌린 상태에서 여전히 가능하다. (아스트라 독립재현 ②)
        locked = self.filtered(
            lambda l: l.check_id.state == "done" or l.check_id.was_done)
        if locked:
            raise ValidationError(_(
                "완료된 적이 있는 점검표(%s)의 항목은 삭제할 수 없습니다.",
                ", ".join(locked.mapped("check_id.name"))))
        parents = self.check_id
        res = super().unlink()
        parents.exists()._check_done_is_complete()
        return res

    @api.constrains("spec_min", "spec_max")
    def _check_spec_range(self):
        for rec in self:
            if rec.spec_min and rec.spec_max and rec.spec_min > rec.spec_max:
                raise ValidationError(_(
                    "'%(item)s' 의 하한(%(low)s) 이 상한(%(high)s) 보다 큽니다.",
                    item=rec.item_name, low=rec.spec_min, high=rec.spec_max,
                ))


class IatfMoldCheckSnapshot(models.Model):
    """금형 점검표 완료 시점의 측정값 전문.

    완료 실적을 고치려면 '작성 중' 으로 되돌려야 한다(값 수정은 그때 열린다). 그런데
    되돌려 고치고 다시 완료하면 **처음 완료했을 때의 측정값이 사라진다.** 심사에서
    묻는 것은 '지금 값' 이 아니라 '그때 그렇게 판정했는가' 이므로, 완료로 넘어갈 때마다
    그 시점의 전문을 여기에 한 벌 얼려 둔다. 개정 차수가 1 씩 올라간다.
    (아스트라 후속 — 완료 전 측정 전체 snapshot 및 새 revision)

    작업환경 점검 실적(`iatf.check.record.snapshot`)과 같은 모양이다. 두 모듈이 서로
    의존하지 않으므로 기존 가드들처럼 나란히 둔다.

    이 원장은 **덧붙이기 전용**이다. 수정도 삭제도 되지 않는다.
    """

    _name = "iatf.mold.check.snapshot"
    _description = "금형 점검 완료 스냅샷"
    _order = "check_id desc, revision desc"

    check_id = fields.Many2one(
        "iatf.mold.check", string="점검", required=True,
        ondelete="cascade", index=True, readonly=True,
    )
    revision = fields.Integer(string="완료 차수", required=True, readonly=True,
                              help="몇 번째 완료인가. 되돌려 고친 뒤 다시 완료하면 1 올라간다.")
    done_at = fields.Datetime(string="완료 시각", required=True, readonly=True)
    done_by_id = fields.Many2one("res.users", string="완료 처리자", readonly=True)
    overall_result = fields.Char(string="그때의 종합 판정", readonly=True)
    ng_count = fields.Integer(string="그때의 이상 항목 수", readonly=True)
    line_count = fields.Integer(string="항목 수", readonly=True)
    content = fields.Text(
        string="측정값 전문", readonly=True,
        help="완료 시점 각 항목의 기준·측정값·판정·비고. 이후 어떤 경로로도 바뀌지 않는다.",
    )
    # ── 완료 당시의 원본 식별 정보 (동결) ──
    # 되돌려 금형·날짜·생산지시를 고치고 재완료하면, 항목 전문만으로는 '그때 무엇을
    # 점검했는지' 를 복원할 수 없었다. 현재 값을 따라가는 related 로 두면 같은 문제다.
    mold_id = fields.Many2one("iatf.mold", string="그때의 금형", readonly=True)
    mold_name = fields.Char(string="그때의 금형(문자)", readonly=True)
    check_type = fields.Char(string="그때의 점검 구분", readonly=True)
    check_date = fields.Date(string="그때의 점검일", readonly=True)
    shift = fields.Char(string="그때의 근무조", readonly=True)
    checker_id = fields.Many2one("res.users", string="그때의 점검자", readonly=True)
    checker_name = fields.Char(string="그때의 점검자(문자)", readonly=True)
    production_name = fields.Char(string="그때의 생산지시", readonly=True)
    company_id = fields.Many2one(
        "res.company", string="그때의 회사", readonly=True,
        help="완료 시점의 회사를 복사해 둔다. 부모의 회사가 바뀌어도 과거 증빙은 그대로다.",
    )
    company_name = fields.Char(string="그때의 회사(문자)", readonly=True)

    _sql_constraints = [
        ("check_revision_uniq", "unique(check_id, revision)",
         "같은 점검표에 같은 완료 차수가 두 번 있을 수 없습니다."),
        ("revision_positive", "CHECK(revision > 0)",
         "완료 차수는 1 이상이어야 합니다."),
    ]

    # 완료 처리 서비스만 이 열쇠를 들고 온다. 열쇠만으로 통과시키지는 않는다 —
    # 아래 create 가 부모 상태를 확인하고 값을 **전부 다시 만든다**.
    _SERVICE_KEY = "iatf_mold_check_snapshot_service"

    @api.model_create_multi
    def create(self, vals_list):
        """완료 처리 과정에서만, 서버가 만든 값으로만 생성된다.

        예전에는 일반 사용자가 초안 부모에 차수·시각·작성자·본문을 지어내어 '완료 증거'
        를 붙일 수 있었다(ACL create=1, readonly 는 서버 검사가 아니다).
        (아스트라 275 리뷰 Q275-01)
        """
        if not self.env.context.get(self._SERVICE_KEY):
            raise ValidationError(_(
                "완료 스냅샷은 점검표를 완료할 때 자동으로 만들어집니다. "
                "직접 추가할 수 없습니다."))
        Check = self.env["iatf.mold.check"]
        prepared = []
        for vals in vals_list:
            check = Check.browse(vals.get("check_id") or 0).exists()
            if not check:
                raise ValidationError(_("스냅샷의 대상 점검표를 찾을 수 없습니다."))
            if check.state != "done":
                raise ValidationError(_(
                    "완료되지 않은 점검표(%s)의 스냅샷은 만들 수 없습니다.", check.name))
            # 호출자가 준 나머지 값은 전부 버린다.
            prepared.append(check._snapshot_values())
        return super().create(prepared)

    def write(self, vals):
        raise ValidationError(_("완료 스냅샷은 수정할 수 없습니다. 증빙 원본입니다."))

    def unlink(self):
        raise ValidationError(_("완료 스냅샷은 삭제할 수 없습니다. 증빙 원본입니다."))
