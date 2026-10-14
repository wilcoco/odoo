from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class IatfSpcSubgroup(models.Model):
    _name = "iatf.spc.subgroup"
    _description = "SPC Subgroup Data"
    _order = "sequence, id"

    study_id = fields.Many2one(
        "iatf.spc.study", string="SPC Study", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(string="Subgroup #", default=10)
    sample_date = fields.Datetime(string="Sample Date", default=fields.Datetime.now)
    operator_id = fields.Many2one("res.users", string="Operator", default=lambda self: self.env.user)

    # Up to 10 individual measurements per subgroup
    x1 = fields.Float(string="X1", digits=(16, 4))
    x2 = fields.Float(string="X2", digits=(16, 4))
    x3 = fields.Float(string="X3", digits=(16, 4))
    x4 = fields.Float(string="X4", digits=(16, 4))
    x5 = fields.Float(string="X5", digits=(16, 4))
    x6 = fields.Float(string="X6", digits=(16, 4))
    x7 = fields.Float(string="X7", digits=(16, 4))
    x8 = fields.Float(string="X8", digits=(16, 4))
    x9 = fields.Float(string="X9", digits=(16, 4))
    x10 = fields.Float(string="X10", digits=(16, 4))

    # 실제로 채워진 표본 수. 0 이면 '부분군 크기 n 전부 입력됨' 으로 본다(수기 입력 호환).
    # 자동 주입(공정검사 → SPC)은 값을 하나씩 채우므로 이 수를 올려 가며 쓴다.
    # 이게 없으면 x1 하나만 넣은 부분군의 x2~x5 가 0 으로 평균에 들어가
    # 10.0 측정 하나가 평균 2.0 / 범위 10 으로 왜곡된다. (제3자 검토 Q14)
    # **입력한 표본 수.** Float 은 '미입력' 과 '0.0' 을 구분하지 못하므로, 유효 측정 0 을
    # 살리려면 "몇 개를 입력했는가" 를 사람이나 자동 주입이 따로 말해 주어야 한다.
    # 이 값이 0 이어도 값이 들어 있는 칸은 입력된 것으로 본다(아래 `_filled_set`).
    # (아스트라 재검토 2026-09-10 ①)
    sample_count = fields.Integer(
        string="입력 표본 수(앞에서부터)", default=0,
        help="앞에서부터 연속으로 몇 칸을 입력했는지. '몇 개를 입력했는가'(개수)가 아니라 "
             "'앞에서부터 어디까지 입력했는가'(구간)를 뜻한다. 측정값이 0 인 칸을 통계에 "
             "넣으려면 이 수를 그 칸까지 올린다. 실제로 입력된 칸 목록은 '입력 칸'이 갖는다.")

    # **입력 칸의 정본.** `sample_count`(앞에서부터 몇 칸)와 '값이 0 이 아닌 칸' 의
    # 합집합으로 입력 여부를 판단하던 규칙은 틀렸다. 개수와 구간을 섞으면
    # x5 만 따로 채워 둔 부분군에 자동 주입이 한 칸 들어갈 때마다 `sample_count` 가
    # 그 앞의 **입력한 적 없는 칸까지** 덮어, 측정 4 개짜리 부분군이 0 을 포함한
    # 5 개 완성군으로 보고된다(아스트라 독립재현 2026-09-10 ①).
    # 그래서 입력된 칸 번호를 그대로 적어 둔다. 빈칸과 측정값 0 을 구분하는 유일한 근거다.
    filled_mask = fields.Char(
        string="입력 칸", readonly=True, copy=False,
        help="실제로 입력된 칸 번호(예: 1,2,5). 값이 없으면 이 기록 이전 자료로 보고 "
             "예전 규칙(앞에서부터 입력 표본 수 + 0 이 아닌 칸)으로 판단한다.")

    origins = fields.Char(string="자동 주입 출처",
                          help="공정검사 라인 키 목록. 같은 판정을 두 번 눌러도 중복 주입되지 않게.")

    # Computed
    sg_mean = fields.Float(string="X̄", digits=(16, 4), compute="_compute_stats", store=True)
    sg_range = fields.Float(string="R", digits=(16, 4), compute="_compute_stats", store=True)
    is_ooc = fields.Boolean(string="Out of Control", default=False)
    # ── 근거불명 군 (아스트라 2026-09-10 후속) ──
    # `filled_mask` 가 없는 기록은 **어느 칸을 실제로 입력했는지 알 수 없다.** 예전
    # 규칙(앞에서부터 표본 수 + 0 이 아닌 칸)으로 읽으면 값이 나오기는 하지만, 그것은
    # 추정이지 근거가 아니다. 원자료와 이미 저장된 보고값은 그대로 두고, **새 자동분석과
    # 새 승인근거 산정에서만** 이런 군을 뺀다. 뺀 건수와 사유는 연구에 표시한다.
    # 자격 표시는 통계(`sg_mean`/`sg_range`)와 **다른 compute** 로 둔다. 같은 compute 에
    # 얹으면 이 필드가 추가되는 업그레이드에서 과거 부분군의 평균·범위까지 다시 계산되어
    # 저장된 통계값이 조용히 바뀐다. 과거 값은 과거 값대로 두어야 한다.
    # (아스트라 275 리뷰 — 이관 시 공유 compute 우려)
    basis_known = fields.Boolean(
        string="입력 근거 있음", compute="_compute_eligibility", store=True,
        help="어느 칸을 실제로 입력했는지가 기록되어 있는가. 이 표시가 없는 과거 기록은 "
             "새 분석에서 제외한다(원자료는 보존).",
    )
    is_analyzable = fields.Boolean(
        string="분석 대상", compute="_compute_eligibility", store=True,
        help="완성 부분군이면서 입력 근거가 있는 군. 관리한계·공정능력은 이것만 쓴다. "
             "**화면의 이 값은 참고용이다** — 계산은 실행 시점에 원자료로 다시 판정한다.",
    )
    analysis_state = fields.Selection(
        [("analyzed", "분석 대상"),
         ("excluded_incomplete", "제외 — 미완성"),
         ("excluded_unknown", "제외 — 근거불명(입력 칸 미기록)")],
        string="분석 상태", compute="_compute_eligibility", store=True,
        help="이번 분석에 쓰였는가. '제외' 인 군의 이탈 표시는 **과거 판정 보존값**이며 "
             "현재 관리한계로 다시 판정한 결과가 아니다.",
    )
    basis_confirmed_by_id = fields.Many2one(
        "res.users", string="입력 칸 확인자", readonly=True, copy=False,
        help="과거 기록의 입력 칸을 실제 기록과 대조해 확인한 사람.")
    basis_confirmed_at = fields.Datetime(
        string="입력 칸 확인 시각", readonly=True, copy=False)
    is_complete = fields.Boolean(
        string="완성 부분군", compute="_compute_stats", store=True,
        help="부분군 크기(n)만큼 표본이 모였는가. 미완성 부분군을 관리도·공정능력에 "
             "넣으면 평균·범위가 왜곡된다. (제3자 재검토 R07)")

    notes = fields.Char(string="Notes")

    _SLOT_FIELDS = ("x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10")

    def _slots(self):
        self.ensure_one()
        return [self[f] for f in self._SLOT_FIELDS]

    _MASK_EMPTY = "-"          # '입력 칸을 관리 중이며, 아직 아무 칸도 입력하지 않았다'

    @staticmethod
    def _parse_mask(text):
        return {int(p) for p in (text or "").split(",") if p.strip().isdigit()}

    @classmethod
    def _dump_mask(cls, slots):
        return ",".join(str(i) for i in sorted(slots)) or cls._MASK_EMPTY

    def _legacy_filled_set(self, n):
        """`filled_mask` 가 없던 시절의 기록을 읽는 규칙.

        새로 쓰는 기록은 전부 mask 를 갖는다. 이 갈래는 이 변경 이전에 저장된
        미확정 자료(입력 칸을 알 수 없는 자료)에만 쓴다.
        """
        self.ensure_one()
        stated = min(max(self.sample_count or 0, 0), n)
        out = set(range(1, stated + 1))
        for i, v in enumerate(self._slots()[:n], start=1):
            if v:
                out.add(i)
        return out

    def _filled_set(self):
        """입력된 칸 번호 집합.

        `filled_mask` 가 정본이다. 별도 필드를 두지 않고 '쓰기가 일어난 칸' 으로
        판단할 수 없는 이유는 그대로다 — Odoo 폼은 화면의 모든 필드를 함께 보낸다.
        그래서 mask 는 **값이 실제로 달라졌거나, 0 이 아닌 값이 들어왔거나,
        사람이 `sample_count` 로 앞에서부터 구간을 밝힌** 칸만 담는다(`write` 참조).
        """
        self.ensure_one()
        n = self.study_id.subgroup_size or 5
        if self.filled_mask:
            return self._parse_mask(self.filled_mask) & set(range(1, n + 1))
        return self._legacy_filled_set(n)

    def _next_free_slot(self):
        """자동 주입이 쓸 다음 빈 칸(1-based). 없으면 0.

        '값이 0 인 칸' 이 아니라 '아직 쓰지 않은 칸' 을 찾는다 — 유효 측정 0 을
        빈칸으로 보면 그 값을 덮어쓴다. (제3자 재검토 R06 / 아스트라 재검토 ①)
        """
        self.ensure_one()
        n = self.study_id.subgroup_size or 5
        filled = self._filled_set()
        for i in range(1, n + 1):
            if i not in filled:
                return i
        return 0

    def _filled_count(self, upto=None):
        """입력된 칸 수. 값이 0 이어도 입력했으면 센다."""
        self.ensure_one()
        n = self.study_id.subgroup_size or 5
        filled = self._filled_set()
        if upto:
            filled = filled | {upto}
        return len(filled & set(range(1, n + 1)))

    def _get_values(self):
        """통계에 쓸 값 — **입력된 칸의 값만**.

        `_filled_set()` 이 정한 칸의 값만 센다. 표본 수를 말해 둔 칸의 0 은 측정값으로
        들어가고, 아무것도 입력하지 않은 부분군은 빈 목록을 돌려준다 — 예전에는 n 개의
        0 을 돌려주어 빈 부분군이 '완성군' 으로 계산에 들어갔다. (아스트라 재검토 ①)
        """
        self.ensure_one()
        n = self.study_id.subgroup_size or 5
        filled = sorted(self._filled_set())
        slots = self._slots()
        return [slots[i - 1] for i in filled]

    def _slot_limit(self, vals=None):
        """이 부분군이 쓸 수 있는 칸 수. 부분군 크기와 측정 칸 수 중 작은 쪽."""
        study = self.study_id
        if not study and vals and vals.get("study_id"):
            study = self.env["iatf.spc.study"].browse(vals["study_id"])
        return min(study.subgroup_size or 5, len(self._SLOT_FIELDS))

    def _assert_sample_count(self, vals, limit):
        """`sample_count` 범위를 **아무것도 만들기 전에** 본다.

        예전에는 `set(range(1, sample_count + 1))` 을 먼저 만들고 그 뒤에 잘라 냈고,
        범위 검사는 `@api.constrains` 라 create 가 끝난 뒤에야 돌았다. 즉 큰 정수
        하나로 그 사이에 거대한 집합을 실제로 할당하게 만들 수 있었다.
        (아스트라 독립재현 2026-09-10 18:48)
        """
        if "sample_count" not in vals:
            return
        try:
            stated = int(vals.get("sample_count") or 0)
        except (TypeError, ValueError):
            raise ValidationError(_(
                "입력 표본 수는 정수여야 합니다: %s", vals.get("sample_count")))
        if not 0 <= stated <= limit:
            raise ValidationError(_(
                "입력 표본 수는 0~%(limit)s 이어야 합니다. 입력값: %(given)s",
                limit=limit, given=stated))

    def _marked_from_vals(self, vals, base):
        """이 write/create 로 '입력했다' 고 볼 칸을 base 에 더해 돌려준다.

        근거는 셋뿐이다.
          - 0 이 아닌 값이 들어온 칸
          - 저장된 값과 달라진 칸 (측정값을 0 으로 고친 경우를 살린다)
          - `sample_count` 로 사람이 밝힌 '앞에서부터 그 칸까지'
        폼이 함께 보내는, 값이 그대로인 빈 칸은 입력으로 세지 않는다.

        결과는 부분군 크기 안으로 잘라 낸다 — 모델이 스스로 만든 mask 는 항상
        유효하고, **밖에서 건네받은** mask 만 `_check_input_slots` 가 거른다.
        (n=5 인데 x7 에 값이 있으면 예전부터 통계에서 빠졌다. 그 동작을 그대로 둔다.)
        """
        marked = set(base)
        for i, name in enumerate(self._SLOT_FIELDS, start=1):
            if name not in vals:
                continue
            new = float(vals.get(name) or 0.0)
            if new:
                marked.add(i)
            elif self and new != float(self[name] or 0.0):
                marked.add(i)
        stated = vals.get("sample_count")
        if stated is None and self:
            stated = self.sample_count
        marked |= set(range(1, max(int(stated or 0), 0) + 1))
        return marked & set(range(1, self._slot_limit(vals) + 1))

    _EVIDENCE_FIELDS = ("filled_mask", "basis_confirmed_by_id", "basis_confirmed_at")

    @api.model_create_multi
    def create(self, vals_list):
        # context default 로도 근거를 심을 수 없다. `default_*` 는 vals 에 없이 들어오므로
        # 값 검사만으로는 못 잡는다 — 아예 걷어낸다. (445 품질 리뷰 (1))
        planted = ["default_%s" % name for name in self._EVIDENCE_FIELDS
                   if self.env.context.get("default_%s" % name) is not None]
        if planted:
            raise ValidationError(_(
                "입력 칸 근거는 기본값으로 지정할 수 없습니다: %s", ", ".join(planted)))
        blank = self.browse()
        # context 로 열어 두는 뒷문을 만들지 않는다. 새 부분군의 입력 칸은 언제나
        # 측정값과 `sample_count` 에서 서버가 정한다. (445 품질 리뷰 (1))
        for vals in vals_list:
            forged = {"basis_confirmed_by_id", "basis_confirmed_at"} & set(vals)
            if forged:
                raise ValidationError(_(
                    "입력 칸 확인 증거(%s)는 직접 만들 수 없습니다.",
                    ", ".join(sorted(forged))))
            if "filled_mask" in vals:
                # 조용히 버리지 않고 거절한다 — 무엇이 무시됐는지 모르는 편이 더 나쁘다.
                # 새 입력의 입력 칸은 측정값과 `sample_count` 로 서버가 정한다.
                raise ValidationError(_(
                    "입력 칸(filled_mask)은 직접 지정할 수 없습니다. 측정값과 "
                    "'입력 표본 수' 로 기록됩니다."))
        for vals in vals_list:
            # 할당 전에 먼저 거른다 — 아래 헬퍼는 이 검사를 통과해야만 불린다.
            blank._assert_sample_count(vals, blank._slot_limit(vals))
            if not vals.get("filled_mask"):
                vals["filled_mask"] = self._dump_mask(
                    blank._marked_from_vals(vals, set()))
                # 표본 수가 군 크기를 넘으면 `_check_input_slots` 가 거른다 — 여기서
                # 조용히 고치지 않는다. 잘못 들어온 사실이 보여야 한다.
        return super().create(vals_list)

    def write(self, vals):
        """입력 칸 정본을 같은 write 에 실어 갱신한다.

        호출자가 `filled_mask` 를 직접 준 경우(자동 주입의 `_record_measurement`)는
        그 값을 그대로 쓴다.
        """
        # [305 품질 리뷰 (1)] `filled_mask` 와 확인 증거를 직접 쓰면 '입력 칸 확인' 을
        # 건너뛰고 근거불명 자료를 근거 있는 자료로 바꿀 수 있다. 확인 증거는 서버가
        # 확정한다 — `action_confirm_input_slots` 와 `_record_measurement`(신규 입력)만
        # 이 검사를 지나지 않는다.
        # [445 품질 리뷰 (1)] context Boolean 은 RPC 로 그대로 넘어오는 직렬화 값이라
        # 권한이 될 수 없다. 내부 경로는 이 `write` 를 아예 거치지 않고
        # `super().write` 를 직접 부른다(`_record_measurement`,
        # `action_confirm_input_slots`). 그래서 여기서는 무조건 거절한다.
        forged = {"filled_mask", "basis_confirmed_by_id",
                  "basis_confirmed_at"} & set(vals)
        if forged:
            raise ValidationError(_(
                "입력 칸 근거(%s)는 직접 쓸 수 없습니다. 과거 기록은 '입력 칸 확인' 으로, "
                "새 측정은 측정값 입력으로 기록됩니다.", ", ".join(sorted(forged))))
        derived = {"basis_known", "is_analyzable", "analysis_state", "is_complete"} & set(vals)
        if derived:
            # 이 표시들은 원자료에서 나오는 결과다. 손으로 바꾸면 제외 규칙이 무력해진다.
            # (아스트라 275 리뷰 Q275-04) 과거 기록을 근거 있는 자료로 인정하려면
            # `action_confirm_input_slots` 로 **실제 입력 칸을 확인**해야 한다.
            raise ValidationError(_(
                "분석 자격 표시(%s)는 직접 바꿀 수 없습니다. 원자료(입력 칸·측정값)에서 "
                "다시 판정됩니다.", ", ".join(sorted(derived))))
        if "sample_count" in vals:
            for rec in self:
                rec._assert_sample_count(vals, rec._slot_limit())
        touches_input = "filled_mask" not in vals and (
            "sample_count" in vals or any(f in vals for f in self._SLOT_FIELDS))
        if not touches_input:
            return super().write(vals)
        for rec in self:
            rec._assert_sample_count(vals, rec._slot_limit())
            if not rec.filled_mask:
                # **근거불명 기록**(이 변경 이전 자료)에는 mask 를 만들지 않는다.
                # 예전에는 추정 집합(`sample_count` 앞 구간 ∪ 비영값)을 base 로 넣고
                # 그대로 명시 mask 로 저장했다. 같은 값을 한 번 다시 저장하기만 해도
                # 확인한 적 없는 0 들이 '확인된 측정' 으로 승격됐다.
                # 승격은 `action_confirm_input_slots` 로만 한다. (275 리뷰 Q275-05)
                super(IatfSpcSubgroup, rec).write(vals)
                continue
            marked = rec._marked_from_vals(vals, rec._filled_set())
            super(IatfSpcSubgroup, rec).write(
                dict(vals, filled_mask=rec._dump_mask(marked)))
        return True

    def action_confirm_input_slots(self):
        """과거 기록의 입력 칸을 **사람이 확인해** 근거로 승격한다.

        단순 저장이나 자동 수집으로는 승격되지 않는다(275 리뷰 Q275-05). 운영자가 실제
        기록지와 대조해 '앞에서부터 몇 칸을 입력했는지'(`sample_count`)를 바로잡은 뒤
        이 버튼을 누른다. 원자료와 기존 분석값은 그대로 둔다 — 자격 표시만 붙는다.
        """
        for rec in self:
            if rec.filled_mask:
                raise UserError(_(
                    "이미 입력 칸이 기록된 부분군입니다(%s). 확인이 필요 없습니다.",
                    rec.filled_mask))
            n = rec._slot_limit()
            stated = min(max(rec.sample_count or 0, 0), n)
            marked = set(range(1, stated + 1))
            for i, value in enumerate(rec._slots()[:n], start=1):
                if value:
                    marked.add(i)
            if not marked:
                raise UserError(_(
                    "입력한 칸이 하나도 없습니다. 실제 기록지를 보고 '입력 표본 수' 를 "
                    "먼저 기입하십시오. (부분군 %s)", rec.sequence))
            super(IatfSpcSubgroup, rec).write({
                "filled_mask": rec._dump_mask(marked),
                "basis_confirmed_by_id": self.env.user.id,
                "basis_confirmed_at": fields.Datetime.now(),
            })
        return True

    def _record_measurement(self, slot, value, origin=None):
        """자동 주입 전용 — 한 칸을 채우고 그 칸을 입력 칸에 명시적으로 더한다.

        `sample_count`(앞에서부터 몇 칸)를 채워진 칸 수로 되받아 쓰면 안 된다.
        개수와 구간이 다른 뜻이기 때문이다(아스트라 독립재현 ①).
        """
        self.ensure_one()
        if not self.filled_mask:
            # 근거불명 군에 한 칸 흘려 넣으면 나머지 추정 칸까지 근거로 승격된다.
            # 자동 수집은 이런 군을 건드리지 않는다 — 새 부분군을 만든다. (Q275-05)
            raise ValidationError(_(
                "입력 칸이 기록되지 않은 과거 부분군에는 자동 주입할 수 없습니다. "
                "'입력 칸 확인' 으로 근거를 확정한 뒤 사용하십시오. (부분군 %s)",
                self.sequence))
        marked = self._filled_set() | {int(slot)}
        vals = {"x%d" % int(slot): value, "filled_mask": self._dump_mask(marked)}
        if origin:
            vals["origins"] = ",".join(filter(None, [self.origins, origin]))
        # 서버 전용 경로 — 사용자 `write` 가드를 지나지 않는다(context 로 열지 않는다).
        self._assert_sample_count(vals, self._slot_limit())
        return super(IatfSpcSubgroup, self).write(vals)

    @api.constrains("sample_count", "filled_mask", "study_id")
    def _check_input_slots(self):
        """입력 칸 정본이 실제로 존재하는 칸만 가리키는지 본다.

        `filled_mask` 는 화면에서 읽기 전용이지만 API·가져오기로는 아무 문자열이나
        들어올 수 있다. 근거가 틀리면 통계가 조용히 틀어진다 — 없는 칸을 가리키면
        평균이 어긋나고, 군 크기를 넘는 표본 수는 영원히 완성군이 되지 못한다.
        (아스트라 후속 과제 — mask 직접쓰기·슬롯 검증)
        """
        for sg in self:
            n = sg.study_id.subgroup_size or 5
            limit = min(n, len(sg._SLOT_FIELDS))
            if sg.sample_count and not 0 <= sg.sample_count <= limit:
                raise ValidationError(_(
                    "입력 표본 수는 0~%(limit)s 이어야 합니다(부분군 크기 %(size)s). 입력값: %(given)s",
                    limit=limit, size=n, given=sg.sample_count))
            raw = sg.filled_mask
            if not raw or raw == sg._MASK_EMPTY:
                continue
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            slots = []
            for part in parts:
                if not part.isdigit() or not 1 <= int(part) <= limit:
                    raise ValidationError(_(
                        "입력 칸(%(mask)s)에 존재하지 않는 칸 '%(slot)s' 이 있습니다. "
                        "1~%(limit)s 만 쓸 수 있습니다.",
                        mask=raw, slot=part, limit=limit))
                slots.append(int(part))
            if len(set(slots)) != len(slots):
                raise ValidationError(_(
                    "입력 칸(%s)에 같은 칸이 두 번 들어 있습니다.", raw))

    def _eligibility(self):
        """**원자료에서 지금 다시 판정한** (근거 있음, 분석 대상, 상태).

        저장된 표시를 믿지 않는다. 저장 필드는 화면 표시용이고, 그것만 외부에서 바꿔
        제외 규칙을 우회할 수 있기 때문이다. 관리한계·공정능력·이탈 판정은 실행 시점에
        이 메서드로 자격을 다시 도출한다. (아스트라 275 리뷰 Q275-04)
        """
        self.ensure_one()
        n = self.study_id.subgroup_size or 5
        known = bool(self.filled_mask)
        complete = len(self._get_values()) >= n
        if not complete:
            return known, False, "excluded_incomplete"
        if not known:
            return False, False, "excluded_unknown"
        return True, True, "analyzed"

    @api.depends("x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10",
                 "sample_count", "filled_mask", "study_id.subgroup_size")
    def _compute_eligibility(self):
        for sg in self:
            sg.basis_known, sg.is_analyzable, sg.analysis_state = sg._eligibility()

    @api.depends("x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10",
                 "sample_count", "filled_mask", "study_id.subgroup_size")
    def _compute_stats(self):
        for sg in self:
            vals = sg._get_values()
            n = sg.study_id.subgroup_size or 5
            sg.is_complete = len(vals) >= n
            if vals:
                sg.sg_mean = sum(vals) / len(vals)
                sg.sg_range = max(vals) - min(vals)
            else:
                sg.sg_mean = 0.0
                sg.sg_range = 0.0
