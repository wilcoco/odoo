from odoo import api, fields, models


class PlanningLine(models.Model):
    _name = "injection.planning.line"
    _description = "생산계획 상세 라인"
    _order = "plan_date, workcenter_id, sequence"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(
        "res.company", related="planning_run_id.company_id",
        store=True, index=True, readonly=True,
        help="계획 실행의 회사를 그대로 따른다. 활성 회사가 아니라 **계획의 회사**여야 "
             "다른 회사 계획의 산출물이 우리 목록에 섞이지 않는다. (PR08)",
    )
    sequence = fields.Integer(string="순서", default=10)
    plan_date = fields.Date(
        string="필요일", required=True, index=True,
        help="이 수량이 필요한 날(수요 기준일). 실제로 언제 만들어지는지는 "
             "'생산 시작일'·'완료일' 이 말한다. (P1-PP05)",
    )
    # ── 필요일과 실제 일정일의 분리 (P1-PP05) ──
    # 예전에는 라인이 필요일 하나만 들고 있었다. 가동시간이 모자라 작업이 다음 날로
    # 밀려도 일별 요약·원재료 소요는 **필요일**로 집계돼, 그날 반제품이 들어온 것처럼
    # 보였다. JIT 조립 결품을 차트가 숨긴다는 뜻이다.
    start_date = fields.Date(
        string="생산 시작일", compute="_compute_schedule_dates", store=True, index=True,
        help="실제로 이 작업이 시작되는 날(현지 시각 기준). 원재료가 소비되는 날이다.",
    )
    finish_date = fields.Date(
        string="생산 완료일", compute="_compute_schedule_dates", store=True, index=True,
        help="실제로 이 작업이 끝나는 날(현지 시각 기준). 양품이 재고로 들어오는 날이다.",
    )

    # ── 배정 ──
    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="사출기", required=True,
    )
    mold_id = fields.Many2one(
        "injection.mold", string="금형", required=True,
    )
    product_id = fields.Many2one(
        "product.product", string="사출 부품", required=True,
    )

    # ── 수량 ──
    demand_qty = fields.Float(string="순수요")
    planned_qty = fields.Float(string="계획 수량", help="불량율 + 초기불량 반영")
    defect_rate = fields.Float(string="적용 불량율 (%)")
    initial_scrap = fields.Integer(string="적용 초기 불량")

    # ── 금형 교체 ──
    changeover_needed = fields.Boolean(string="금형 교체 필요")
    changeover_count = fields.Integer(
        string="교체 횟수",
        compute="_compute_changeover_count", store=True,
        help="금형 교체 필요 시 1, 아니면 0 (피벗 합계용)",
    )
    changeover_hours = fields.Float(string="교체 시간 (h)")

    # ── 시간 ──
    production_hours = fields.Float(
        string="생산 시간 (h)", compute="_compute_hours", store=True,
    )
    total_hours = fields.Float(
        string="총 소요 시간 (h)", compute="_compute_hours", store=True,
    )
    start_time = fields.Datetime(string="시작 예정")
    end_time = fields.Datetime(string="종료 예정")
    shift = fields.Selection(
        [("day", "주간"), ("night", "야간")],
        string="교대",
        help="이 라인이 놓인 가동 구간의 교대. 라인은 항상 한 교대 안에 들어간다.",
    )
    fit_unverified = fields.Boolean(
        string="적합성 미확인", index=True,
        help="필수 적합성 자료(예: 사출기 형체력)가 마스터에 없어 이 배정이 물리적으로 "
             "가능한지 확인되지 않았다. 0 을 '부족' 으로 단정하지 않되, 확인 전에는 "
             "계획 확정·MO 생성을 막는다. (P1-PP06)",
    )
    fit_note = fields.Char(
        string="미확인 사유", help="어떤 자료가 없어서 확인하지 못했는지.",
    )
    is_late = fields.Boolean(
        string="납기 초과", compute="_compute_schedule_dates", store=True, index=True,
        help="완료일이 필요일보다 늦은 라인. 가동시간이 모자라 뒤로 밀린 것을 "
             "차트가 숨기지 않게 표시한다. (P1-PP05/PP06)",
    )

    # ── 재고 ──
    current_stock = fields.Float(string="현재 재고")
    max_inventory = fields.Float(string="최대 재고")
    occupancy_start_time = fields.Datetime(
        string="설비 점유 시작", readonly=True,
        help="교체만 한 앞 구간이 있으면 그 시작 시각. 생산은 `start_time` 부터지만 "
             "설비·금형은 이때부터 잡혀 있다. 다른 계획의 예약 조회가 이 시간을 "
             "포함해야 같은 창을 두 번 예약하지 않는다.")
    changeover_in_span_hours = fields.Float(
        string="이 구간 내 교체시간", readonly=True,
        help="이 계획 라인의 시작~종료 안에서 실제로 소비된 금형 교체 시간. "
             "교체가 앞 구간(전날 등)에서 끝났으면 0 이다. 제조오더 소요시간을 "
             "계산할 때 교체를 이중으로 더하지 않기 위한 원천이다.")

    # ── [R135] 일별 사출기 순서와 교체 출처 ──
    daily_sequence = fields.Integer(
        string="일별 순서", index=True,
        help="같은 사출기·같은 작업일(`start_date`) 안의 1,2,3… 순서. 계산이 시작 시각에서 유도해 채운다. "
             "담당자가 고친 뒤 「수동 순서 적용」 을 누르면 그 순서로 시간을 다시 놓는다(초안·MO 없는 라인만).")
    changeover_source = fields.Selection(
        [("capability", "조합 교체시간(확인된 값, 0 포함)"),
         ("mold_confirmed", "금형 교체시간(담당자 확인)"),
         ("mold_unconfirmed", "금형 교체시간(기존 값·출처 미확인)"),
         ("none_same_mold", "교체 없음(같은 금형 연속)")],
        string="교체시간 출처", readonly=True,
        help="[R135 Q4] 적용한 교체시간 **값**이 어디서 왔는지. 미확인 값은 기본값이었다고 단정하지 않는다.")
    mount_unknown = fields.Boolean(
        string="장착 금형 미확인", readonly=True,
        help="[R135 검토 #3] 전날 장착 기록이 없어 교체 여부를 알 수 없었다 — 교체로 가정했다. "
             "교체시간 값의 출처와는 **다른 사실**이라 따로 둔다.")
    changeover_start_time = fields.Datetime(string="교체 시작", readonly=True)
    changeover_end_time = fields.Datetime(string="교체 종료", readonly=True)
    expected_good_qty = fields.Float(
        string="예상 양품", readonly=True,
        help="(계획 수량 − 초기불량) × (1 − 불량률). 재고 궤적에는 이 값이 들어간다. 총생산량과 다르다.")
    projected_stock_end = fields.Float(
        string="완료일 예상 잔고", readonly=True,
        help="이 라인 완료일 말의 제품 예상 재고(예상 양품 기준 최종 궤적).")
    due_end_time = fields.Datetime(
        string="납기 상한", readonly=True,
        help="필요일의 업무 종료(23:59:59, 교대 시간대). 일자 수요만 있어 시각 납기·BR 2시간은 여기서 입증하지 않는다.")

    # ── MO 연결 ──
    mo_id = fields.Many2one("mrp.production", string="제조 오더", readonly=True)

    state = fields.Selection(
        [("draft", "초안"), ("confirmed", "확정"), ("done", "완료")],
        string="상태",
        default="draft",
    )

    # 이 필드들이 바뀌면 일별 요약·원재료 소요·발주 판단의 근거가 달라진다.
    # (`state`·`mo_id` 는 실행 결과라 파생값을 바꾸지 않는다.)
    _DERIVED_INPUTS = frozenset((
        "planning_run_id",
        "planned_qty", "demand_qty", "product_id", "mold_id", "workcenter_id",
        "plan_date", "start_time", "end_time", "defect_rate", "initial_scrap",
    ))

    def _mark_derived_stale(self):
        """계획을 손으로 고쳤다 — 파생 결과가 옛 값이라는 사실을 계획에 남긴다. (P1-PP07)

        예전에는 라인만 바뀌고 원재료 소요·차트·발주량은 계산 당시 값 그대로였다.
        화면의 계획 총계는 맞아 보이므로 어긋난 것을 알아채기 어렵다.
        """
        runs = self.mapped("planning_run_id").filtered(
            lambda r: r.state in ("review", "confirmed"))
        if runs:
            runs.sudo().write({"derived_stale": True})

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._mark_derived_stale()
        return records

    def write(self, vals):
        # [275 계획 리뷰 (1)] 부모를 옮기면 **떠난 계획과 도착한 계획 둘 다** 파생 결과가
        # 옛 값이 된다. 예전에는 어느 쪽에도 표시가 서지 않아, 라인을 옮기는 것만으로
        # 두 계획의 소요·발주 근거를 조용히 어긋나게 할 수 있었다.
        sources = self.mapped("planning_run_id") if "planning_run_id" in vals else None
        res = super().write(vals)
        if self._DERIVED_INPUTS & set(vals) or sources is not None:
            self._mark_derived_stale()
        if sources is not None:
            sources.exists().filtered(
                lambda r: r.state in ("review", "confirmed")
            ).sudo().write({"derived_stale": True})
        return res

    def unlink(self):
        runs = self.mapped("planning_run_id")
        res = super().unlink()
        runs.exists().filtered(
            lambda r: r.state in ("review", "confirmed")
        ).sudo().write({"derived_stale": True})
        return res

    @api.depends("start_time", "end_time", "plan_date")
    def _compute_schedule_dates(self):
        """UTC 로 저장된 배치 시각을 현장의 날짜로 되돌린다.

        시각을 UTC 날짜로 그냥 자르면 야간 교대가 하루 밀린다(한국은 UTC+9).
        교대 판정과 같은 시간대 원천을 쓴다.
        """
        config = self.env["injection.planning.config"]._get_active_shift_config()
        for rec in self:
            start = config.utc_to_shift_local(rec.start_time) if (config and rec.start_time) else False
            end = config.utc_to_shift_local(rec.end_time) if (config and rec.end_time) else False
            rec.start_date = start.date() if start else rec.plan_date
            rec.finish_date = end.date() if end else rec.plan_date
            rec.is_late = bool(
                rec.finish_date and rec.plan_date and rec.finish_date > rec.plan_date)

    @api.depends("changeover_needed")
    def _compute_changeover_count(self):
        for rec in self:
            rec.changeover_count = 1 if rec.changeover_needed else 0

    @api.depends("planned_qty", "changeover_hours", "changeover_needed")
    def _compute_hours(self):
        for rec in self:
            cap = self.env["injection.machine.mold.capability"].search([
                ("workcenter_id", "=", rec.workcenter_id.id),
                ("mold_id", "=", rec.mold_id.id),
            ], limit=1)
            if cap and cap.hourly_capacity > 0:
                rec.production_hours = rec.planned_qty / cap.hourly_capacity
            else:
                rec.production_hours = 0.0
            co = rec.changeover_hours if rec.changeover_needed else 0.0
            rec.total_hours = rec.production_hours + co
