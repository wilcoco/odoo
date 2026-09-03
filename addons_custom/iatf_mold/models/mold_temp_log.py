from odoo import api, fields, models, _

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

    # 대조에 쓴 기준. 화면에서 "무엇과 비교해 부적합인지" 를 바로 보여주려고 둔다.
    # 마스터를 고치면 따라 움직여야 하므로 저장하지 않는다.
    spec_min = fields.Float(string="기준 하한(℃)", compute="_compute_spec", digits=(16, 1))
    spec_max = fields.Float(string="기준 상한(℃)", compute="_compute_spec", digits=(16, 1))

    spec_result = fields.Selection(
        [("ok", "적합"), ("ng", "부적합"), ("no_spec", "기준 없음")],
        string="합부 판정", compute="_compute_spec_result", store=True,
        help="금형 마스터의 상·하한과 대조한 결과. 기준이 없으면 '부적합' 이 아니라 "
             "'기준 없음' 이다 — 판정하지 않은 것과 불합격은 다른 사실이다.",
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

    @api.depends("mold_id", "log_type",
                 "mold_id.preheat_temp_min", "mold_id.preheat_temp_max",
                 "mold_id.mold_temp_min", "mold_id.mold_temp_max")
    def _compute_spec(self):
        for rec in self:
            kind = rec._spec_kind()
            if rec.mold_id and kind:
                rec.spec_min, rec.spec_max = rec.mold_id._temp_spec(kind)
            else:
                rec.spec_min = rec.spec_max = 0.0

    @api.depends("temperature", "mold_id", "log_type",
                 "mold_id.preheat_temp_min", "mold_id.preheat_temp_max",
                 "mold_id.mold_temp_min", "mold_id.mold_temp_max")
    def _compute_spec_result(self):
        for rec in self:
            kind = rec._spec_kind()
            if not rec.mold_id or not kind:
                rec.spec_result = "no_spec"
            else:
                rec.spec_result = rec.mold_id.check_temp_in_spec(rec.temperature, kind)

    @api.depends("mold_id", "log_type", "measured_at", "point")
    def _compute_display_name(self):
        types = dict(self._fields["log_type"].selection)
        points = dict(self._fields["point"].selection)
        for rec in self:
            stamp = fields.Datetime.to_string(rec.measured_at) if rec.measured_at else ""
            rec.display_name = "%s · %s(%s) · %s" % (
                rec.mold_id.name or _("금형 미지정"),
                types.get(rec.log_type, ""), points.get(rec.point, ""), stamp,
            )
