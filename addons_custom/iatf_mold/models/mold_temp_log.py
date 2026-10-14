from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# 로그 유형 → 금형 마스터의 어느 온도 기준과 대조할지.
# 판정 자체는 iatf.mold.check_temp_in_spec() 하나만 쓴다. 여기에 상·하한 비교를
# 다시 구현하면 기준이 두 벌이 되고, 한쪽만 고쳐지는 순간 증빙이 어긋난다.
SPEC_KIND_BY_LOG_TYPE = {"preheat": "preheat", "operating": "mold"}


class IatfMoldTempLog(models.Model):
    """금형 예열/가동중 온도 측정 이력 — SQ 4_6·4_7.

    크리아 4_7 지적이 "적외선 온도계로 고정측/이동측 측정 방식 개선 필요" 였다.
    측정 부위(고정/이동)와 측정 방식을 **필수 입력**으로 두면, 어느 부위를 무엇으로
    쟀는지가 모든 기록에 남아 그 지적을 선제적으로 막는다.
    """

    _name = "iatf.mold.temp.log"
    _description = "금형 예열/온도 측정 이력 (SQ 4_6·4_7)"
    _inherit = ["mail.thread"]
    _order = "measured_at desc, id desc"
    _rec_name = "display_name"

    mold_id = fields.Many2one(
        "iatf.mold", string="금형", required=True, index=True, tracking=True,
        ondelete="restrict",
    )
    log_type = fields.Selection(
        [("preheat", "예열"), ("operating", "가동중 온도")],
        string="측정 구분", required=True, default="preheat", tracking=True,
        help="예열은 '예열 상·하한', 가동중 온도는 '금형온도 상·하한' 과 대조한다.",
    )
    measured_at = fields.Datetime(
        string="측정 일시", required=True, default=fields.Datetime.now, tracking=True,
    )
    shift = fields.Selection(
        [("day", "주간"), ("evening", "야간"), ("night", "심야")],
        string="근무조", default="day",
    )
    method = fields.Selection(
        [("ir", "적외선"), ("contact", "접촉식"), ("sensor", "설비센서")],
        # 필수다. 무엇으로 쟀는지가 없으면 측정값의 신뢰도를 설명할 수 없다.
        string="측정 방식", required=True, default="ir",
    )
    point = fields.Selection(
        [("fixed", "고정측"), ("moving", "이동측")],
        # 필수다. 크리아 4_7 감점이 정확히 이 부위 구분이 없던 건이다.
        string="측정 부위", required=True, default="fixed",
    )
    temperature = fields.Float(string="측정 온도(℃)", required=True, digits=(16, 1))

    # 대조에 쓴 기준 — **측정 시점의 스냅샷**이다. 마스터를 나중에 고쳐도 안 바뀐다.
    #
    # 처음엔 "마스터를 고치면 따라 움직여야 한다" 며 비저장으로 뒀고, 테스트도 그걸
    # 정상으로 기대했다. 틀렸다. 상한을 90→100 으로 넓히면 과거의 95℃ 부적합이
    # 화면에서 적합으로 바뀐다 — 심사에서 "이 값이 왜 부적합이었나" 에 답할 수 없고,
    # 판정 기록을 소급 변조하는 시스템이 된다. 점검 시트(`iatf.check.record.line`)와
    # 같은 원칙: 실적은 그때 기준을 들고 있는다. (2026-09-10 제3자 검토 Q11)
    # **계산 필드가 아니다.** `create` 에서 한 번 박고 그 뒤로는 아무 것도 다시 쓰지 않는다.
    #
    # 앞선 수정은 `compute="_compute_spec"` + `depends("mold_id","log_type")` 이었다.
    # 그러면 같은 금형 ID 를 다시 write 하는 것만으로 재계산이 돌아 스냅샷이 현행 마스터로
    # 갈아치워진다 — 상한 90 으로 부적합이던 기록이, 마스터를 100 으로 고친 뒤 금형을
    # 재입력하면 적합으로 뒤집힌다. 재현: 제3자 재검토 R03. 계산으로 두는 한 트리거를
    # 하나씩 막는 방식으로는 새는 곳이 계속 생기므로, 아예 계산에서 떼어낸다.
    spec_min = fields.Float(string="기준 하한(℃)", readonly=True, digits=(16, 1),
                            help="측정 시점 마스터 기준의 스냅샷. 이후 어떤 경로로도 바뀌지 않는다.")
    spec_max = fields.Float(string="기준 상한(℃)", readonly=True, digits=(16, 1))

    spec_result = fields.Selection(
        [("ok", "적합"), ("ng", "부적합"), ("no_spec", "기준 없음")],
        string="합부 판정", readonly=True,
        help="측정 당시 기준(스냅샷)과 대조한 결과. 기준이 없으면 '부적합' 이 아니라 "
             "'기준 없음' 이다 — 판정하지 않은 것과 불합격은 다른 사실이다.",
    )
    # 현행 마스터 기준으로 다시 봤을 때의 참고값. 판정(spec_result)이 아니다.
    current_spec_result = fields.Selection(
        [("ok", "적합"), ("ng", "부적합"), ("no_spec", "기준 없음")],
        string="현행 기준 재평가(참고)", compute="_compute_current_spec_result",
        help="지금 마스터 기준으로 보면 어떤가. 기준 개정 뒤 과거 기록을 되짚을 때 쓰는 "
             "참고값이며, 증빙 판정은 측정 당시 기준의 '합부 판정' 이다.",
    )

    production_id = fields.Many2one("mrp.production", string="관련 생산지시")
    measured_by_id = fields.Many2one(
        "res.users", string="측정자", default=lambda self: self.env.user,
    )
    notes = fields.Char(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    def _spec_kind(self):
        self.ensure_one()
        return SPEC_KIND_BY_LOG_TYPE.get(self.log_type)

    # 측정 사실 — 기록된 뒤에는 바꿀 수 없다. 잘못 쟀으면 취소하고 다시 측정한다.
    # 이 목록에 있는 필드를 열어 두면 스냅샷·판정을 우회로 갈아치울 수 있다.
    _MEASUREMENT_FACTS = ("mold_id", "log_type", "measured_at", "point", "method",
                          "temperature", "spec_min", "spec_max", "spec_result")

    @api.model_create_multi
    def create(self, vals_list):
        """측정 시점 기준을 스냅샷으로 박고, 그 기준으로 판정한다.

        계산 필드로 두지 않는 이유는 필드 주석 참조 (R03).
        """
        Mold = self.env["iatf.mold"]
        for vals in vals_list:
            mold = Mold.browse(vals.get("mold_id")) if vals.get("mold_id") else Mold
            kind = SPEC_KIND_BY_LOG_TYPE.get(vals.get("log_type", "preheat"))
            low = high = 0.0
            if mold and kind:
                low, high = mold._temp_spec(kind)
            # 호출자가 넘긴 값은 무시한다 — 스냅샷은 마스터에서만 온다.
            vals["spec_min"], vals["spec_max"] = low, high
            vals["spec_result"] = Mold.judge_temp(vals.get("temperature", 0.0), low, high)
        return super().create(vals_list)

    def write(self, vals):
        """측정 사실은 고칠 수 없다. 비고·연결 생산지시만 열어 둔다."""
        touched = [f for f in self._MEASUREMENT_FACTS if f in vals]
        if touched and self:
            labels = {f: (self._fields[f].string or f) for f in touched}
            raise ValidationError(_(
                "측정 기록은 수정할 수 없습니다: %(names)s\n"
                "잘못 측정했다면 기록을 취소하고 다시 측정하십시오. (변경 항목: %(fields)s)",
                names=", ".join(self.mapped("display_name")[:3]),
                fields=", ".join(labels[f] for f in touched)))
        return super().write(vals)

    @api.depends("temperature", "mold_id", "log_type",
                 "mold_id.preheat_temp_min", "mold_id.preheat_temp_max",
                 "mold_id.mold_temp_min", "mold_id.mold_temp_max")
    def _compute_current_spec_result(self):
        for rec in self:
            kind = rec._spec_kind()
            if not rec.mold_id or not kind:
                rec.current_spec_result = "no_spec"
            else:
                rec.current_spec_result = rec.mold_id.check_temp_in_spec(rec.temperature, kind)

    @api.depends("mold_id", "log_type", "measured_at", "point")
    def _compute_display_name(self):
        types = dict(self._fields["log_type"].selection)
        points = dict(self._fields["point"].selection)
        for rec in self:
            # 사용자 시간대로. UTC 그대로 찍으면 09:55 측정이 "00:55" 로 보여
            # 측정 시각 증빙이 9시간 어긋난다. (화면 리허설 P2)
            stamp = ""
            if rec.measured_at:
                stamp = fields.Datetime.context_timestamp(rec, rec.measured_at).strftime("%Y-%m-%d %H:%M")
            rec.display_name = "%s · %s(%s) · %s" % (
                rec.mold_id.name or _("금형 미지정"),
                types.get(rec.log_type, ""), points.get(rec.point, ""), stamp,
            )
