import math
import logging

import psycopg2
import pytz
from collections import defaultdict
from markupsafe import Markup
from datetime import datetime, time as datetime_time, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)


class PlanningRun(models.Model):
    _name = "injection.planning.run"
    _description = "사출 생산계획 실행"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="계획 번호",
        required=True,
        readonly=True,
        default=lambda self: _("New"),
        copy=False,
    )
    plan_date_from = fields.Date(string="계획 시작일", required=True, tracking=True)
    plan_date_to = fields.Date(string="계획 종료일", required=True, tracking=True)
    schedule_not_before = fields.Datetime(
        string="배정 시작 하한", tracking=True, copy=False,
        help="당일 재계획 시 이미 지난 시간을 다시 배정하지 않도록 지정합니다. "
             "교체 구간도 이 시각 이후에 배정합니다. 비워 두면 기존 일자 기준을 사용합니다.")
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("calculating", "계산중"),
            ("review", "검토"),
            ("confirmed", "확정"),
            ("done", "완료"),
            ("cancelled", "취소"),
        ],
        string="상태",
        default="draft",
        tracking=True,
    )
    demand_ids = fields.Many2many(
        "production.demand",
        "injection_planning_demand_rel",
        "planning_id",
        "demand_id",
        string="수요 데이터",
    )
    line_ids = fields.One2many(
        "injection.planning.line", "planning_run_id", string="계획 라인",
    )
    mo_ids = fields.One2many(
        "mrp.production", "planning_run_id", string="생성된 MO",
    )
    summary_ids = fields.One2many(
        "injection.planning.daily.summary", "planning_run_id",
        string="일별 요약",
    )
    material_requirement_ids = fields.One2many(
        "injection.planning.material.requirement", "planning_run_id",
        string="원재료 소요",
    )
    material_daily_ids = fields.One2many(
        "injection.planning.material.daily", "planning_run_id",
        string="원재료 일별 추이",
    )
    material_po_ids = fields.One2many(
        "purchase.order", "injection_planning_run_id", string="원재료 발주서",
    )
    violation_ids = fields.One2many(
        "injection.planning.violation", "planning_run_id", string="계획 위반",
        help="[R135] 납기 지연·안전재고 부족·최대재고 초과·조기생산. 조용히 정상 확정하지 않는다.")
    feasibility = fields.Selection(
        [("feasible", "하드 위반 없음"),
         ("infeasible_proven", "불가능 — 자원 총량 부족 입증"),
         ("infeasible_unresolved", "미해결 — 휴리스틱이 해를 못 찾음(불가능 증명 아님)")],
        string="실행 가능성", readonly=True, copy=False,
        help="[R135 검토 #1] 두 값으로 불가능을 증명하지 않는다. '입증' 은 같은 자원의 미결 작업 합이 납기까지 "
             "가용시간을 넘는 하한 계산이고, '미해결' 은 탐색이 끝났을 뿐이다.")
    safety_stock_days_applied = fields.Integer(
        string="적용 안전재고 일수", readonly=True, copy=False,
        help="[R135] 이 계획을 계산할 때 적용한 일수. 설정이 바뀌어도 이 계획은 그대로다.")
    safety_stock_basis_applied = fields.Selection(
        [("calendar_days", "달력일 D+1~D+N"), ("demand_dates", "다음 N개 수요가 있는 날짜")],
        string="적용 안전재고 기준", readonly=True, copy=False)
    settings_changed = fields.Boolean(
        string="설정 변경됨(재계산 필요)", compute="_compute_settings_changed",
        help="[R135] 계산 뒤 안전재고 일수·계산 방식 설정이 바뀌었다. 초안으로 되돌려 재계산하기 전엔 확정할 수 없다.")
    sequencing_mode_snapshot = fields.Selection(
        [("legacy", "기존"), ("setup_aware", "교체 인식")], string="계산 당시 방식", readonly=True, copy=False,
        help="[R135 Q3] 이 계획을 계산할 때의 설정. 설정을 바꿔도 이 계획은 그대로다.")
    violations_acknowledged = fields.Boolean(
        string="정책 위반 확인함", readonly=True, copy=False,
        help="[R135 검토 #4] 정책 위반(재고 범위)이 있는 계획을 관리자가 명시적으로 확인했을 때만 확정할 수 있다.")
    violations_acknowledged_by = fields.Many2one("res.users", readonly=True, copy=False)
    sequencing_note = fields.Text(string="순서 계산 안내", readonly=True, copy=False)
    total_changeovers = fields.Integer(string="총 교체 횟수", readonly=True, copy=False)
    late_qty = fields.Float(string="납기 지연 수량", readonly=True, copy=False)
    safety_shortfall_qty = fields.Float(string="안전재고 부족 수량", readonly=True, copy=False)
    max_excess_qty = fields.Float(string="최대재고 초과 수량", readonly=True, copy=False)
    early_qty = fields.Float(string="조기생산 수량", readonly=True, copy=False)
    unassigned_ids = fields.One2many(
        "injection.planning.unassigned", "planning_run_id", string="미배정 수요",
        help="설비·금형의 물리 제약으로 배정하지 못한 수요. 경고로 넘기지 않고 여기에 남긴다.",
    )
    unassigned_count = fields.Integer(
        string="미배정 건수", compute="_compute_stats", store=True,
    )
    late_line_count = fields.Integer(
        string="납기 초과 라인", compute="_compute_stats", store=True,
        help="필요일보다 늦게 끝나도록 배치된 계획 라인 수.",
    )
    derived_stale = fields.Boolean(
        string="파생 결과 재검증 필요", copy=False,
        help="계획 라인을 손으로 고친 뒤 원재료 소요·일별 차트가 다시 계산되지 않았다. "
             "'소요 재검증' 을 누르기 전까지 발주·확정을 막는다. (P1-PP07)",
    )
    theoretical_qty = fields.Float(
        string="이론 최대 생산량", compute="_compute_stats", store=True,
        help="풀 캐퍼 정책이 요구한 수량. 금형 설치·교체 시간을 세지 않은 이론치라 "
             "실제로 배정된 수량과 다르다. 이 값을 생산 가능량으로 읽지 말 것.",
    )
    unassigned_qty = fields.Float(
        string="미배정 부족 수량", compute="_compute_stats", store=True,
    )
    changeover_hours_total = fields.Float(
        string="금형 교체·설치 시간 (h)", compute="_compute_stats", store=True,
        help="이론 최대치와 실제 배정량의 차이를 만드는 주된 원인.",
    )
    unverified_line_count = fields.Integer(
        string="적합성 미확인 라인", compute="_compute_stats", store=True,
        help="필수 적합성 자료가 없어 물리적 가능 여부를 확인하지 못한 라인 수. "
             "0 건이 되어야 확정·MO 생성이 열린다.",
    )
    mo_count = fields.Integer(compute="_compute_stats", store=True)
    material_shortage_count = fields.Integer(
        string="원재료 부족 품목", compute="_compute_stats", store=True,
    )
    material_po_count = fields.Integer(
        string="원재료 발주 건수", compute="_compute_stats", store=True,
    )
    total_planned_qty = fields.Float(
        string="총 계획 수량", compute="_compute_stats", store=True,
    )
    total_changeovers = fields.Integer(
        string="총 금형 교체", compute="_compute_stats", store=True,
    )
    demand_source_filter = fields.Selection(
        [("all", "전체"), ("oracle", "오라클(ERP)"), ("test", "테스트"),
         ("manual", "수동 입력"), ("forecast", "예측"), ("order", "수주")],
        string="수요 소스", default="all", required=True,
        help="'수요 불러오기' 시 이 소스의 수요만 로드 — 양산 전 테스트 수요와 "
             "오라클 실계획을 분리해 계획할 수 있다")
    notes = fields.Text(string="비고")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    @api.depends(
        "line_ids", "line_ids.planned_qty", "line_ids.changeover_needed",
        "line_ids.is_late", "line_ids.fit_unverified", "line_ids.changeover_hours",
        "mo_ids", "unassigned_ids", "unassigned_ids.qty",
        "material_requirement_ids.is_short", "material_po_ids",
    )
    def _compute_stats(self):
        for rec in self:
            rec.mo_count = len(rec.mo_ids)
            rec.total_planned_qty = sum(rec.line_ids.mapped("planned_qty"))
            rec.total_changeovers = len(rec.line_ids.filtered("changeover_needed"))
            rec.material_shortage_count = len(
                rec.material_requirement_ids.filtered("is_short")
            )
            rec.material_po_count = len(rec.material_po_ids)
            rec.unassigned_count = len(rec.unassigned_ids)
            rec.late_line_count = len(rec.line_ids.filtered("is_late"))
            rec.unverified_line_count = len(rec.line_ids.filtered("fit_unverified"))
            rec.unassigned_qty = sum(rec.unassigned_ids.mapped("qty"))
            rec.changeover_hours_total = sum(
                line.changeover_hours for line in rec.line_ids
                if line.changeover_needed)
            # 이론 최대치 = 실제로 배정한 것 + 넣지 못한 것. 둘을 분명히 나눠 보여 준다.
            rec.theoretical_qty = rec.total_planned_qty + rec.unassigned_qty

    @api.depends("safety_stock_days_applied", "safety_stock_basis_applied", "sequencing_mode_snapshot", "state")
    def _compute_settings_changed(self):
        for run in self:
            if run.state not in ("review",) or not run.sequencing_mode_snapshot:
                run.settings_changed = False
                continue
            config = run._get_config()
            run.settings_changed = (
                int(round(config.safety_stock_days or 0)) != run.safety_stock_days_applied
                or config._safety_stock_basis() != run.safety_stock_basis_applied
                or config.sequencing_mode != run.sequencing_mode_snapshot)

    @staticmethod
    def _safety_stock_target(demand_by_date, date_str, safety_days, basis, horizon_end):
        """[R135] 안전재고 목표 — 계산·요약·평가가 **같은 함수**를 쓴다.

        basis='calendar_days': D+1 ~ D+N 달력일의 수요 합(수요 없는 날도 기간에 포함).
        basis='demand_dates' : D 뒤 N개 '수요가 있는 날짜' 의 수요 합(기존 의미).
        돌려주는 값: (목표수량, 수요범위충분 여부). 달력일 기준에서 D+N 이 수집된 수요의 마지막 날짜를
        넘으면 범위 부족(False) — 미수집을 0 수요로 단정하지 않는다.
        """
        if not safety_days:
            return 0.0, True
        if basis == "calendar_days":
            day = fields.Date.to_date(date_str)
            total, complete = 0.0, True
            for offset in range(1, int(safety_days) + 1):
                target_day = str(day + timedelta(days=offset))
                if horizon_end is not None and target_day > horizon_end:
                    complete = False
                total += demand_by_date.get(target_day, 0.0)
            return total, complete
        future = [d for d in sorted(demand_by_date) if d > date_str][:int(safety_days)]
        return sum(demand_by_date[d] for d in future), len(future) == int(safety_days) or not future

    def write(self, vals):
        """`derived_stale` 를 손으로 내려 재검증을 건너뛰지 못하게 한다.

        [275 계획 리뷰 (1)] 이 표시는 '라인을 고쳤다' 는 사실이지 설정값이 아니다.
        내릴 수 있는 곳은 실제로 파생 결과를 다시 만든 두 경로뿐이다 —
        `action_calculate_plan` 과 `action_revalidate_requirements`.
        """
        if "schedule_not_before" in vals and any(r.state != "draft" for r in self):
            raise UserError(_("배정 시작 하한은 초안에서만 변경할 수 있습니다. 초안으로 되돌린 뒤 다시 계산하십시오."))
        if "derived_stale" in vals and not vals["derived_stale"]:
            # [305 계획 리뷰 (1)] 예전에는 context 플래그로 통과시켰다. context 는 RPC 로
            # 그대로 넘어오는 직렬화 값이라 권한이 될 수 없다. 이제 내리는 길은
            # `_clear_derived_stale()` 뿐이고, 그 메서드는 이 검사를 지나지 않는다.
            raise UserError(_(
                "'소요 재검증 필요' 표시는 직접 내릴 수 없습니다. "
                "'소요 재검증' 을 실행하면 자동으로 내려갑니다."))
        return super().write(vals)

    def _clear_derived_stale(self):
        """파생 결과를 실제로 다시 만든 뒤에만 부르는 내부 경로. 위 검사를 지나지 않는다."""
        super(PlanningRun, self.sudo()).write({"derived_stale": False})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                # 번호의 연월은 생성일이 아니라 계획 시작월(R144 정책 ②, 2026-09-15)
                seq_date = fields.Date.to_date(vals.get("plan_date_from")) if vals.get("plan_date_from") else None
                vals["name"] = (
                    self.env["ir.sequence"].with_context(ir_sequence_date=seq_date).next_by_code("injection.planning.run")
                    or _("New")
                )
        return super().create(vals_list)

    # ─────────────────────────────────────────────
    # 수요 데이터 로드
    # ─────────────────────────────────────────────
    def action_load_demands(self):
        """기존 production.demand에서 기간 내 수요 로드"""
        self.ensure_one()
        Demand = self.env["production.demand"]

        domain = [
            ("demand_date", ">=", self.plan_date_from),
            ("demand_date", "<=", self.plan_date_to),
            ("state", "in", ("draft", "confirmed")),
        ]
        if self.demand_source_filter and self.demand_source_filter != "all":
            domain.append(("source", "=", self.demand_source_filter))
        demands = Demand.search(domain)

        self.demand_ids = [(6, 0, demands.ids)]
        self.message_post(body=_("수요 데이터 %d건 로드 (소스: %s)") % (
            len(demands),
            dict(self._fields["demand_source_filter"].selection).get(
                self.demand_source_filter, "전체")))
        return True

    def action_fetch_demand(self):
        """Oracle에서 수요 데이터 로드.

        erp_plan_sync 설치 시: 수신을 그 원장(스테이징+멱등 갱신)에 위임한다 —
        오라클 수요의 정본은 하나(이중 수신·이중 계상 방지). 이 버튼은 수동
        트리거 역할만 하고, 아래 직접 조회 로직은 모듈 미설치 환경의 폴백이다.
        """
        self.ensure_one()
        if "erp.plan.sync" in self.env:
            sync = self.env["erp.plan.sync"].create({})
            sync.action_fetch()
            sync.action_push_demands()
            self.action_load_demands()
            self.message_post(body=_(
                "ERP 수요 수신을 erp_plan_sync 원장에 위임 — 배치 %(name)s "
                "(수요 생성 %(c)d·갱신 %(u)d, 품번 미매칭 %(m)d)") % {
                    "name": sync.name, "c": sync.demand_created,
                    "u": sync.demand_updated, "m": sync.unmatched_count})
            return True
        config = self._get_config()

        unmapped = {}
        try:
            demands = self.with_context(unmapped_codes=unmapped)._fetch_from_oracle(config)
        except Exception as e:
            _logger.exception("Oracle 수요 조회 실패")
            raise models.UserError(f"Oracle 수요 조회 실패: {e}")

        # 기존 Oracle 수요는 연결 해제 (삭제하지 않음)
        self.demand_ids = [(5, 0, 0)]

        if demands:
            # 같은 (제품, 날짜) 수요를 합산
            merged = defaultdict(float)
            hourly_merged = defaultdict(float)
            for d in demands:
                key = (d["product_id"], d["demand_date"], d["demand_type"])
                if d["demand_type"] == "hourly":
                    hkey = (d["product_id"], d["demand_date"], d.get("hour", 0))
                    hourly_merged[hkey] += d["quantity"]
                else:
                    merged[key] += d["quantity"]

            create_vals = []
            for (pid, dd, dtype), qty in merged.items():
                create_vals.append({
                    "demand_date": dd,
                    "product_id": pid,
                    "quantity": qty,
                    "demand_type": dtype,
                    "source": "oracle",
                })
            for (pid, dd, hour), qty in hourly_merged.items():
                create_vals.append({
                    "demand_date": dd,
                    "product_id": pid,
                    "quantity": qty,
                    "demand_type": "hourly",
                    "hour": hour,
                    "source": "oracle",
                })

            new_demands = self.env["production.demand"].create(create_vals)
            self.demand_ids = [(6, 0, new_demands.ids)]
            daily_cnt = len(merged)
            hourly_cnt = len(hourly_merged)
            self.message_post(
                body=f"Oracle에서 수요 데이터를 가져왔습니다. "
                     f"(일별 {daily_cnt}건, 시간별 {hourly_cnt}건, "
                     f"총 {sum(d['quantity'] for d in create_vals):.0f}개)"
            )
        else:
            self.message_post(body="Oracle에서 가져온 수요 데이터가 없습니다.")
        # [안전망 S1] 품목 미매핑으로 조용히 제외된 품번을 채터에 보고
        if unmapped:
            self.message_post(body=Markup(
                "<b>⚠ 품목 미매핑으로 제외된 수요 품번 %d종</b> — 품목 마스터 등록 필요:<br/>"
                % len(unmapped)
                + ", ".join("%s(%d행)" % (k, v) for k, v in sorted(unmapped.items())[:30])))

    def action_add_manual_demand(self):
        """수동 수요 입력 폼 열기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "수요 추가",
            "res_model": "production.demand",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_source": "manual",
                "default_demand_date": str(self.plan_date_from),
            },
        }

    def action_import_demand_file(self):
        """CSV 파일에서 수요 데이터 임포트 (Oracle 대체)"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "수요 파일 업로드",
            "res_model": "injection.import.demand.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_planning_run_id": self.id},
        }

    def action_generate_availability(self):
        """계획 기간에 대해 사출기 가동 일정 일괄 생성 (없는 것만)"""
        self.ensure_one()
        self._assert_company_scope()
        config = self._get_config()
        Avail = self.env["injection.machine.availability"]
        # [275 계획 리뷰 (4)] 다른 회사의 호기에 우리 계획의 가동일정을 만들지 않는다.
        domain = []
        if self.company_id:
            domain = ["|", ("company_id", "=", False),
                      ("company_id", "=", self.company_id.id)]
        workcenters = self.env["mrp.workcenter"].search(domain)
        if not workcenters:
            raise UserError(_("이 계획의 회사에 등록된 사출기(작업장)가 없습니다."))

        created = 0
        current = self.plan_date_from
        while current <= self.plan_date_to:
            for wc in workcenters:
                existing = Avail.search([
                    ("workcenter_id", "=", wc.id),
                    ("date", "=", current),
                ], limit=1)
                if not existing:
                    Avail.create({
                        "workcenter_id": wc.id,
                        "date": current,
                        # [275 계획 리뷰 (3)] 여기에도 `or 8.0` 이 남아 있었다.
                        # "야간 안 돌린다"(0h)는 설정이 일괄 생성에서 8시간으로 부활한다.
                        "day_shift_hours": config.day_shift_hours or 0.0,
                        "night_shift_hours": config.night_shift_hours or 0.0,
                    })
                    created += 1
            current += timedelta(days=1)

        self.message_post(
            body=f"가동 일정 {created}건 생성 완료 "
                 f"({len(workcenters)}대 x {(self.plan_date_to - self.plan_date_from).days + 1}일)"
        )
        # 가동 일정 리스트 열기
        return {
            "type": "ir.actions.act_window",
            "name": "사출기 가동 일정",
            "res_model": "injection.machine.availability",
            "view_mode": "list,form",
            "domain": [
                ("date", ">=", str(self.plan_date_from)),
                ("date", "<=", str(self.plan_date_to)),
            ],
            "context": {"search_default_group_wc": 1},
        }

    def _get_config(self):
        """이 계획의 **회사** 설정을 쓴다.

        [305 계획 리뷰 (5)] `_get_active_shift_config()` 는 활성 회사 기준이라,
        회사 A 에서 회사 B 계획을 계산하면 A 의 교대 시간·불량률 기본값으로 돈다.
        """
        Config = self.env["injection.planning.config"]
        company = (self.company_id if len(self) == 1 and self.company_id
                   else self.env.company)
        config = Config._get_active_shift_config(company=company)
        if not config:
            raise UserError(_(
                "회사 '%s' 의 생산계획 설정이 없습니다. 먼저 설정을 생성하세요.",
                company.display_name))
        return config

    def _fetch_from_oracle(self, config):
        """Oracle DB에서 수요 조회 (피벗 테이블 → 언피벗)"""
        conn = config._get_oracle_connection()
        demands = []
        try:
            cursor = conn.cursor()

            # ── T_ZM_PLN2: 일별 수요 (D00~D12, 13일) ──
            daily_table = config.daily_table or "T_ZM_PLN2"
            daily_cols = [f"D{i:02d}" for i in range(13)]  # D00~D12

            if config.demand_query_daily:
                cursor.execute(config.demand_query_daily)
            else:
                col_list = ", ".join(daily_cols)
                query = f"""
                    SELECT YMD, ITM, CHASU, LINE, FR, CSRT, ALC, {col_list}
                    FROM {daily_table}
                    WHERE YMD >= :d1 AND YMD <= :d2
                    ORDER BY YMD, ITM
                """
                d1 = self.plan_date_from.strftime("%Y%m%d")
                d2 = self.plan_date_to.strftime("%Y%m%d")
                cursor.execute(query, d1=d1, d2=d2)

            if not config.demand_query_daily:
                for row in cursor:
                    ymd_str = row[0]       # '20250911'
                    itm = row[1]           # 품번
                    # row[2]~row[6]: CHASU, LINE, FR, CSRT, ALC (참조 정보)
                    base_date = datetime.strptime(ymd_str, "%Y%m%d").date()

                    for i, col in enumerate(daily_cols):
                        qty = row[7 + i] or 0
                        if qty <= 0:
                            continue
                        demand_date = base_date + timedelta(days=i)
                        # 계획 기간 내만
                        if demand_date < self.plan_date_from or demand_date > self.plan_date_to:
                            continue
                        product = self._find_product_by_code(itm)
                        if product:
                            demands.append({
                                "demand_date": str(demand_date),
                                "product_id": product.id,
                                "quantity": float(qty),
                                "demand_type": "daily",
                                "source": "oracle",
                                "planning_run_id": self.id,
                            })

            # ── T_ZM_PLN1: 시간별 수요 (5일 × 10시간) ──
            hourly_table = config.hourly_table or "T_ZM_PLN1"
            # 컬럼 매핑: (컬럼명, day_offset, hour)
            hourly_col_map = []
            for day in range(5):
                # 시간 1~8: D{day}01R ~ D{day}08R
                for hour in range(1, 9):
                    col_name = f"D{day:02d}{hour}R"
                    hourly_col_map.append((col_name, day, hour))
                # 시간 9: D{day}9R
                col_name = f"D{day:02d}9R"
                hourly_col_map.append((col_name, day, 9))
                # 시간 10: D{day}10R
                col_name = f"D{day:01d}{day:01d}10R" if day == 0 else f"D{day:02d}10R"
                # 실제 컬럼명 패턴: D0010R, D0110R, D0210R, D0310R, D0410R
                col_name = f"D{day:02d}10R"
                hourly_col_map.append((col_name, day, 10))

            hourly_end = min(
                self.plan_date_from + timedelta(days=5),
                self.plan_date_to,
            )

            if config.demand_query_hourly:
                cursor.execute(config.demand_query_hourly)
            else:
                col_list = ", ".join(c[0] for c in hourly_col_map)
                query = f"""
                    SELECT YMD, ITM, CHASU, LINE, FR, CSRT, ALC, {col_list}
                    FROM {hourly_table}
                    WHERE YMD >= :d1 AND YMD <= :d2
                    ORDER BY YMD, ITM
                """
                d1 = self.plan_date_from.strftime("%Y%m%d")
                d2 = hourly_end.strftime("%Y%m%d")
                cursor.execute(query, d1=d1, d2=d2)

            if not config.demand_query_hourly:
                for row in cursor:
                    ymd_str = row[0]
                    itm = row[1]
                    base_date = datetime.strptime(ymd_str, "%Y%m%d").date()

                    for i, (col_name, day_offset, hour) in enumerate(hourly_col_map):
                        qty = row[7 + i] or 0
                        if qty <= 0:
                            continue
                        demand_date = base_date + timedelta(days=day_offset)
                        if demand_date < self.plan_date_from or demand_date > self.plan_date_to:
                            continue
                        product = self._find_product_by_code(itm)
                        if product:
                            demands.append({
                                "demand_date": str(demand_date),
                                "product_id": product.id,
                                "quantity": float(qty),
                                "demand_type": "hourly",
                                "hour": hour,
                                "source": "oracle",
                                "planning_run_id": self.id,
                            })

            _logger.info(
                "Oracle 수요 조회 완료: 일별 %d건, 시간별 %d건",
                len([d for d in demands if d["demand_type"] == "daily"]),
                len([d for d in demands if d["demand_type"] == "hourly"]),
            )
        finally:
            conn.close()

        return demands

    def _find_product_by_code(self, code):
        """제품 코드로 product.product 검색"""
        if not code:
            return None
        product = self.env["product.product"].search(
            ["|", ("default_code", "=", code), ("barcode", "=", code)],
            limit=1,
        )
        if not product:
            _logger.warning("제품 코드 '%s'에 해당하는 제품 없음", code)
            um = self.env.context.get("unmapped_codes")
            if um is not None:
                um[code] = um.get(code, 0) + 1
        return product

    # ─────────────────────────────────────────────
    # 계산 산출물(파생 원장) 기록 권한 — P1-PP03
    # ─────────────────────────────────────────────
    #
    # 계획 라인·일별 요약·원재료 소요/일별추이는 **시스템이 계산해 낸 결과**다.
    # 계획 담당자에게 이 원장의 create/unlink 권한을 직접 주면 산출 수량과
    # 가용재고를 손으로 고칠 수 있게 된다 — 그건 결함을 고치는 게 아니라 결함을
    # 옮기는 것이다. 그래서 ACL 은 담당자에게 읽기만 남기고(관리자만 전권),
    # **역할·회사·상태를 확인한 계산 훅 안에서만** 제한적으로 sudo 로 기록한다.
    #
    # 계산 본체(BOM 전개·재고 조회·배정)는 사용자 권한 그대로 돈다. 여기서 넓히는
    # 것은 '자기 회사 계획의 계산 결과를 남기는 것' 하나뿐이다.
    _LEDGER_STATES = ("draft", "calculating", "review")

    def _planning_ledger(self, allowed_states=_LEDGER_STATES):
        """계산 산출물을 쓸 수 있는 제한 권한 recordset 을 돌려준다."""
        self.ensure_one()
        user = self.env.user
        if not user.has_group("injection_planning.group_planning_user"):
            raise AccessError(_(
                "생산계획 담당자 권한이 없어 계획을 계산할 수 없습니다. (%s)", self.name))
        if self.company_id and self.company_id not in user.company_ids:
            # 남의 회사 계획을 대신 계산해 주는 경로는 만들지 않는다.
            raise AccessError(_(
                "다른 회사(%(company)s)의 계획은 계산할 수 없습니다. (%(name)s)",
                company=self.company_id.display_name, name=self.name))
        if self.state not in allowed_states:
            raise UserError(_(
                "'%(state)s' 상태에서는 계산 산출물을 다시 쓸 수 없습니다. (%(name)s)",
                state=dict(self._fields["state"].selection).get(self.state, self.state),
                name=self.name))
        return self.sudo()

    # ─────────────────────────────────────────────
    # 계획 계산 (스케줄링 엔진)
    # ─────────────────────────────────────────────
    def action_calculate_plan(self):
        """메인 스케줄링 알고리즘"""
        self.ensure_one()
        # C3 동일 패턴(서버 가드): 검토/확정 단계에서 재계산 차단 — UI 버튼은 draft에서만 보이지만
        # RPC 직접호출·상태전이로 우회되면 검토 중 수동조정한 계획 라인이 유실되므로 서버에서도 막는다.
        # 재계산은 '초안으로'(action_reset_draft)로 명시 초기화 후 진행.
        if self.state not in ("draft", "calculating"):
            raise UserError(_(
                "이미 계산된 계획입니다. 재계산하려면 먼저 '초안으로'를 눌러 초기화하세요.\n"
                "(검토 단계에서 수동 조정한 계획 라인이 유실되지 않도록 보호합니다.)"))
        if self.plan_date_from > self.plan_date_to:
            raise UserError(_("계획 종료일은 시작일 이후여야 합니다."))
        past = self.demand_ids.filtered(
            lambda d: d.state in ("draft", "confirmed") and d.demand_date < self.plan_date_from)
        if past:
            raise UserError(_(
                "계획 시작일 이전 수요가 포함되어 있습니다. 완료 수요를 제외하고, 미납 잔량은 "
                "납기와 수량을 확인한 별도 수요로 등록하십시오. 과거 전체 수요를 다시 생산하지 않습니다."))
        ledger = self._planning_ledger(("draft", "calculating"))
        self.state = "calculating"
        ledger.line_ids.unlink()
        ledger.unassigned_ids.unlink()
        ledger.violation_ids.unlink()

        config = self._get_config()
        super(PlanningRun, self.sudo()).write({
            "sequencing_mode_snapshot": config.sequencing_mode, "violations_acknowledged": False,
            "violations_acknowledged_by": False,
            "safety_stock_days_applied": int(round(config.safety_stock_days or 0)),
            "safety_stock_basis_applied": config._safety_stock_basis()})

        # [안전망] 계산 중 '조용한 건너뜀'(미전개·조합없음 등)을 수집해 완료 시 채터 보고
        plan_issues = []
        self = self.with_context(plan_issues=plan_issues, r135_caps={}, r135_search_stats={})

        def _post_issues():
            if plan_issues:
                self.message_post(body=Markup(
                    "<b>⚠ 계획 계산 경고 %d건</b><br/>" % len(plan_issues)
                    + "<br/>".join("· " + i for i in plan_issues)))

        # 1단계: BOM 전개 (완성품 → 사출 부품)
        part_demands = self._explode_bom()

        if not part_demands:
            self._generate_daily_summary(part_demands, config)
            self._calculate_material_requirements()
            self._clear_derived_stale()
            self.state = "review"
            self.message_post(body="BOM 전개 결과 사출 부품 수요가 없습니다.")
            _post_issues()
            return

        # 2단계: 순수요 계산 (재고 차감, 최대재고 제한)
        net_demands = self._calculate_net_requirements(part_demands)

        if not net_demands:
            # 생산이 0이어도 현재고·기존 예정입고가 수요를 어떻게 충당하는지 남긴다.
            self._generate_daily_summary(part_demands, config)
            self._calculate_material_requirements()
            self._clear_derived_stale()
            self.state = "review"
            self.message_post(body="현재 가용재고와 확인된 예정입고로 수요 충족 예정. 추가 생산 불필요.")
            _post_issues()
            return

        # 3단계: 사출기 배정 + 수량 조정 + 스케줄링
        demand_series = defaultdict(dict)
        for (pid, date_str), qty in part_demands.items():
            demand_series[pid][date_str] = demand_series[pid].get(date_str, 0.0) + qty
        lines_data, unassigned = self.with_context(r135_demand=dict(demand_series))._schedule(net_demands, config)

        # 3-1단계: 물리 제약에 걸려 배정하지 못한 수요를 큐에 남긴다 (P1-PP06)
        if unassigned:
            self._planning_ledger(("calculating",)).env[
                "injection.planning.unassigned"].create(unassigned)
            self.message_post(body=Markup(
                "<b>⚠ 미배정 수요 %d건</b> — 설비·금형 제약으로 배정하지 못했습니다."
                % len(unassigned)))

        # 4단계: 계획 라인 생성
        if lines_data:
            self._planning_ledger(("calculating",)).env[
                "injection.planning.line"].create(lines_data)
            self.message_post(
                body=f"계획 계산 완료: {len(lines_data)}건 라인, "
                     f"총 {sum(d['planned_qty'] for d in lines_data):.0f}개 생산 예정"
            )

        # 5단계: 일별 요약 생성 (차트용)
        self._generate_daily_summary(part_demands, config)

        # 6단계: 원재료 소요/재고 집계 (확정 검토용)
        self._calculate_material_requirements()

        # [R135] 7단계: 일별 사출기 순서 유도 + 최종 궤적(예상 양품) 검사·위반 기록
        self._assign_daily_sequence()
        self._evaluate_plan(part_demands, config)

        _post_issues()
        # 방금 계산했으므로 파생 결과가 최신이다 (표시를 내릴 수 있는 두 경로 중 하나)
        self._clear_derived_stale()
        self.state = "review"

    def _explode_bom(self):
        """BOM 전개: 완성품 수요 → 사출 부품별 수요

        컬러가 다른 완제품이라도 같은 사출 부품이 BOM에 등록되어 있으므로,
        BOM 전개 결과 사출 부품 단위로 자연스럽게 수요가 합산됨.
        예) 86500-BS000EBB 80개 + 86500-BS000SWP 40개
            → 프론트 범퍼 쉘 120개, 브라켓 240개
        """
        # {(product_id, date_str): qty}
        part_demands = defaultdict(float)
        issues = self.env.context.get("plan_issues")

        # [G1] 사출품 판정: is_injection_part(injection_worksite 설치 시) 또는 capability 보유
        cap_pids = set()
        for c in self._company_capabilities():
            cpid = c.product_id.id or c.mold_id.product_id.id
            if cpid:
                cap_pids.add(cpid)

        def _is_inj(prod):
            tmpl = prod.product_tmpl_id
            if tmpl._fields.get("is_injection_part") and tmpl.is_injection_part:
                return True
            return prod.id in cap_pids

        # 재계산 멱등성: draft 뿐 아니라 이전 계산으로 confirmed 된 수요도 재전개 대상에 포함.
        #   (calculate_plan 재실행 시 draft 가 없어 계획이 0으로 비워지던 데이터손실 방지.
        #    이미 생산완료(done)·취소(cancelled) 수요는 제외.)
        for demand in self.demand_ids.filtered(lambda d: d.state in ("draft", "confirmed")):
            Bom = self.env["mrp.bom"]
            jit_category = self.env.ref(
                "escon_bom_util.product_category_jit_assembly",
                raise_if_not_found=False,
            )
            if _is_inj(demand.product_id):
                purpose = "injection"
                allow_standard = False
            elif jit_category and demand.product_id.categ_id == jit_category:
                purpose = "vehicle_batch"
                allow_standard = False
            else:
                purpose = "general_assembly"
                allow_standard = True
            bom = Bom.find_for_purpose(
                demand.product_id, purpose,
                allow_standard_fallback=allow_standard,
            )

            # 수요 제품 자체가 사출품이면 BOM(원재료) 보유 여부와 무관하게 자체 수요.
            # (기존: BOM 있으면 하위만 추출 → 원재료 BOM 가진 사출품 수요가 소실되던 결함)
            if _is_inj(demand.product_id):
                part_demands[(demand.product_id.id, str(demand.demand_date))] += demand.quantity
                demand.state = "confirmed"
                continue
            if not bom or not bom.bom_line_ids:
                # BOM 없으면: 사출품이면 자체 수요로 간주, 비사출이면 제외+경고
                if _is_inj(demand.product_id):
                    part_demands[(demand.product_id.id, str(demand.demand_date))] += demand.quantity
                elif issues is not None:
                    issues.append(
                        "BOM 없음+비사출 수요 제외: %s (%s, %.0f개)"
                        % (demand.product_id.default_code or demand.product_id.name,
                           demand.demand_date, demand.quantity))
                demand.state = "confirmed"
                continue

            # BOM 라인에서 사출 부품 추출 → 사출품 기준으로 합산
            # BOM 기준수량을 완제품 UoM 으로 변환 (라인/BOM 이 다른 단위로 등록돼도 정확)
            bom_qty_base = bom.product_uom_id._compute_quantity(
                bom.product_qty, bom.product_tmpl_id.uom_id, round=False) or 1.0
            for line in bom.bom_line_ids:
                # [G1] 비사출 구성품(외주 체결구·클립 등)은 사출 계획에서 제외
                if not _is_inj(line.product_id):
                    continue
                line_qty = line.product_uom_id._compute_quantity(
                    line.product_qty, line.product_id.uom_id, round=False)
                qty_per = line_qty / bom_qty_base
                part_demands[(line.product_id.id, str(demand.demand_date))] += (
                    demand.quantity * qty_per
                )

            demand.state = "confirmed"

        return dict(part_demands)

    def _company_capabilities(self):
        """이 계획의 회사가 실제로 쓸 수 있는 사출기-금형 조합.

        PR08: 조합 검색에 회사 조건이 없어서, 회사 B 계획이 회사 A 의 호기·금형에
        배정됐다. 조합 자체에는 회사가 없으므로 호기와 금형의 회사로 거른다.
        (회사가 비어 있는 공용 마스터는 그대로 쓴다.)
        """
        self.ensure_one()
        caps = self.env["injection.machine.mold.capability"].search(
            [("active", "=", True)])
        company = self.company_id
        if not company:
            return caps
        return caps.filtered(
            lambda c: c.mold_id.company_id in (False, company)
            and c.workcenter_id.company_id in (False, company))

    def _open_mo_receipts(self, product_ids):
        """아직 만들어지지 않은 MO 의 잔량을 **확인 가능한 입고**와 **지연 예정량**으로 나눈다.

        P1-PP04: 예전에는 진행 중 MO 의 잔량을 **날짜 없이** 초기 재고에 전량 더했다.
        10일 뒤 완료 예정인 MO 100 개가 오늘 쓸 수 있는 재고로 잡혀 "오늘 생산 불필요"
        가 되고, 실제 조립은 결품이 난다.

        **완료 예정일이 이미 지난 MO 는 입고로 세지 않는다.** 계획 시작일에 확실히
        들어온다고 단정하면 결품을 다시 가리게 된다(아스트라 2026-09-10 18:56).
        그 수량은 `지연 예정량` 으로 따로 돌려주어 화면에 표시만 한다. 실행 가능한
        재고로 쓰려면 사람이 그 MO 를 명시적으로 재예정해야 한다.

        돌려주는 값: ({제품: {완료 예정일: 수량}}, {제품: 지연 예정량})
        """
        self.ensure_one()
        receipts = defaultdict(lambda: defaultdict(float))
        overdue = defaultdict(float)
        if not product_ids:
            return receipts, overdue
        MO = self.env["mrp.production"]
        domain = [("product_id", "in", list(product_ids)),
                  ("state", "in", ("confirmed", "progress", "to_close"))]
        if "is_ip_unit_mo" in MO._fields:
            domain.append(("is_ip_unit_mo", "=", False))
        if self.company_id:
            # 다른 회사의 진행 물량을 우리 가용재고로 세지 않는다.
            domain.append(("company_id", "=", self.company_id.id))
        config = self._get_config()
        start = self.plan_date_from
        for mo in MO.search(domain):
            pending = (mo.product_qty or 0.0) - (mo.qty_produced or 0.0)
            if pending <= 0:
                continue
            due = mo.date_finished or mo.date_start
            local = config.utc_to_shift_local(due) if due else False
            due_date = local.date() if local else False
            if not due_date or due_date < start:
                overdue[mo.product_id.id] += pending
                _logger.info("[순수요] 지연 예정량(가용 제외) %s +%.1f (%s, 예정 %s)",
                             mo.product_id.default_code, pending, mo.name, due_date or "-")
                continue
            receipts[mo.product_id.id][due_date] += pending
            _logger.info("[순수요] 예정입고 %s +%.1f @ %s (%s)",
                         mo.product_id.default_code, pending, due_date, mo.name)
        return receipts, overdue

    def _scheduled_receipts(self, product_ids):
        """확인 가능한 예정 입고만. 지연분은 `_open_mo_receipts` 로 따로 본다."""
        return self._open_mo_receipts(product_ids)[0]

    def _planning_on_hand(self, products):
        """Extension point for quality usability, retaining the caller's stock scope.

        [R144 테스트 확정] 코어 `stock/models/product.py` 의 `qty_available` 캐시 키
        (`depends_context`)에는 `strict` 가 없는데 `_get_domain_locations` 는 `strict` 를 읽는다.
        그래서 같은 `location` 문맥에서 `strict=True` 로 먼저 읽힌 0 이, `_stock_scope` 가
        `strict` 를 떼어낸 recordset 에도 같은 캐시 키로 돌아와 Stock 자식 선반 재고가 0 이
        됐다(순수요 과대). 캐시를 거치지 않고 정규화된 문맥으로 직접 계산한다.
        """
        if not products:
            return {}
        ctx = products.env.context
        quantities = products._compute_quantities_dict(
            ctx.get("lot_id"), ctx.get("owner_id"), ctx.get("package_id"),
            ctx.get("from_date"), ctx.get("to_date"))
        return {product.id: quantities[product.id]["qty_available"] for product in products}

    def _calculate_net_requirements(self, part_demands):
        """순수요 계산 — 풀 캐퍼 생산, 향후 3일치 안전재고

        생산 원칙:
        ① 생산이 필요한 날은 해당 제품 기계의 풀 캐퍼(일 가용시간)로 생산
        ② 당일 부족 없어야 함 (최우선)
        ③ 향후 N일 수요를 충당할 안전재고 확보
        ④ 최대 재고 초과 방지
        running_stock으로 (생산 + 소비) 모두 정확히 추적.
        """
        config = self._get_config()
        safety_days = int(round(config.safety_stock_days or 0))
        safety_basis = config._safety_stock_basis()
        demand_horizon_end = max((d for _p, d in part_demands.keys()), default=None)

        net = {}
        r135_caps = self.env.context.get("r135_caps")
        if r135_caps is None:
            r135_caps = {}
        # 제품별로 재고 한번만 조회
        product_ids = set(pid for pid, _ in part_demands.keys())
        products = self.env["product.product"].browse(list(product_ids))
        max_inv_map = {p.id: p.max_inventory_qty for p in products}

        # running_stock: 생산·소비 모두 반영하는 실시간 재고. **오늘 손에 있는 것**만
        # 초기값이다. 진행 중 MO 의 잔량은 완료 예정일이 되어야 더한다 (P1-PP04).
        # 그래야 어제 확정한 MO 를 오늘 또 계획하는 이중 계획도 막히고, 아직 만들어지지
        # 않은 물량을 오늘 쓸 수 있다고 보지도 않는다.
        running_stock = self._stock_on_hand(products)
        receipts, overdue = self._open_mo_receipts(product_ids)
        applied_receipt_dates = defaultdict(set)
        _iss = self.env.context.get("plan_issues")
        for pid, qty in overdue.items():
            product = self.env["product.product"].browse(pid)
            message = ("지연 예정량 %.0f개(가용재고에서 제외): %s — 완료 예정일이 지난 "
                       "미완료 MO 입니다. 재예정 전에는 실행 가능 재고로 세지 않습니다."
                       % (qty, product.default_code or product.name))
            _logger.warning("[순수요] %s", message)
            if _iss is not None:
                _iss.append(message)

        def _receive_upto(pid, upto):
            """(지금까지 반영한 날) ~ upto 까지 도착하는 예정 입고를 재고에 더한다."""
            for due, qty in sorted(receipts.get(pid, {}).items()):
                if due <= upto and due not in applied_receipt_dates[pid]:
                    running_stock[pid] = running_stock.get(pid, 0.0) + qty
                    applied_receipt_dates[pid].add(due)

        for p in products:
            _logger.info(
                "[순수요] 제품 %s (id=%s): usable_stock=%.1f, max_inv=%.1f",
                p.default_code, p.id, running_stock.get(p.id, 0), max_inv_map.get(p.id, 0),
            )

        # 제품별 일일 풀 캐퍼 계산 (최적 사출기-금형 조합 기준)
        capabilities = self._company_capabilities()
        # [PR07] 여기서도 명시적 0 을 살린다. 순수요의 '풀 캐퍼' 가 배정 가능 시간과
        # 어긋나면, 야간을 안 돌리는 공장에 야간 몫까지 얹어 계획한다.
        daily_hours = (config.day_shift_hours or 0.0) + (config.night_shift_hours or 0.0)

        # capability → product 매핑: related 필드 대신 mold_id.product_id 직접 참조
        product_daily_cap = {}
        for pid in product_ids:
            caps = [
                c for c in capabilities
                if (c.product_id.id == pid) or (c.mold_id.product_id.id == pid)
            ]
            if caps:
                # [G4] 유효능력(불량률 반영) 기준 — 배정 선택 기준과 일치
                def _eff(c):
                    dr = c.defect_rate or 0.0   # 조합에 적힌 값이 정본(0 은 0)
                    return c.hourly_capacity * max(0.0, 1.0 - dr / 100.0)
                best = max(caps, key=_eff)
                product_daily_cap[pid] = _eff(best) * daily_hours
                _logger.info(
                    "[순수요] 제품 id=%s: daily_cap=%.1f (hourly=%.1f × %dh)",
                    pid, product_daily_cap[pid], best.hourly_capacity, daily_hours,
                )
            else:
                _logger.warning(
                    "[순수요] 제품 id=%s: capability 없음! 풀캐퍼 계산 불가", pid,
                )
                _iss = self.env.context.get("plan_issues")
                if _iss is not None:
                    _p = self.env["product.product"].browse(pid)
                    _iss.append("capability 없음(풀캐퍼 정책 미적용): %s"
                                % (_p.default_code or _p.name))

        # 제품별 날짜→수요 매핑 (향후 N일 참조용)
        product_date_demand = defaultdict(dict)
        for (pid, date_str), qty in part_demands.items():
            product_date_demand[pid][date_str] = qty

        # 제품별 전체 날짜 정렬
        product_sorted_dates = {}
        for pid in product_ids:
            dates = sorted(product_date_demand[pid].keys())
            product_sorted_dates[pid] = dates

        # 계획 기간 내 날짜만 생산 (기간 외 수요는 안전재고 참조용)
        plan_end_str = str(self.plan_date_to)
        sorted_keys = sorted(part_demands.keys(), key=lambda k: k[1])

        for (pid, date_str) in sorted_keys:
            # 계획 기간 밖의 수요는 건너뜀 (안전재고 참조로만 사용)
            if date_str > plan_end_str:
                continue
            required = part_demands[(pid, date_str)]
            _receive_upto(pid, fields.Date.to_date(date_str))
            current = running_stock.get(pid, 0)
            max_inv = max_inv_map.get(pid, 0)

            # [R135] 안전재고 목표 — 요약·평가와 같은 함수. 기존 방식은 이전 의미(수요가 있는 날짜 수) 그대로.
            future_demand, _complete = self._safety_stock_target(
                product_date_demand[pid], date_str, safety_days, safety_basis, demand_horizon_end)

            # 목표: 당일 소비 후에도 향후 N일 수요를 충당할 재고 확보
            after_consume = current - required
            need = future_demand - after_consume

            # ① 당일 부족: 소비 후 재고 < 0이면 반드시 생산
            if after_consume < 0:
                need = max(need, -after_consume)

            # 생산 불필요
            if need <= 0:
                _logger.info(
                    "[순수요] SKIP pid=%s %s: current=%.1f req=%.1f "
                    "after=%.1f future=%.1f need=%.1f",
                    pid, date_str, current, required,
                    after_consume, future_demand, need,
                )
                running_stock[pid] = after_consume
                continue

            if config.sequencing_mode == "setup_aware":
                # [R135 §4.1 · R141 F1] 얼마나 **필요한가**만 정하되, **실수요**와 **안전재고 선행량**을 다른 항목으로 둔다.
                # 선행량은 그것이 덮는 실수요의 날짜를 납기로 갖는다 — 첫날 납기로 재분류하면 하드 지연으로 둔갑한다
                # (독립시험 83fa660 F1). 하루 풀 캐퍼로 부풀리지 않는다(아스트라 Q2).
                headroom = (max_inv - after_consume) if max_inv > 0 else None
                real = math.ceil(max(0.0, -after_consume))                       # 당일 부족(상한보다 우선)
                remaining_headroom = None if headroom is None else max(0.0, headroom - real)
                if real > 0:
                    net[(pid, date_str)] = net.get((pid, date_str), 0) + real
                    r135_caps[(pid, date_str)] = headroom
                stock_after = after_consume + real
                # 선행량: D+1.. 의 실수요를 그 날짜 항목으로 미리 만든다(재고 상한 여유 안에서). 상한 때문에 못 만드는 몫은
                # 정책 위반(안전재고 부족)으로 평가 단계가 기록한다 — 하드가 아니다.
                budget = None if remaining_headroom is None else remaining_headroom
                cover_dates = ([str(fields.Date.to_date(date_str) + timedelta(days=k)) for k in range(1, safety_days + 1)]
                               if safety_basis == "calendar_days" else
                               [d for d in product_sorted_dates.get(pid, []) if d > date_str][:safety_days])
                covered = 0.0
                for cover in cover_dates:
                    want = product_date_demand[pid].get(cover, 0.0)
                    if want <= 0:
                        continue
                    # 이미 재고로 덮이는 만큼은 뺀다
                    already = max(0.0, stock_after - covered)
                    piece = max(0.0, want - already)
                    if budget is not None:
                        piece = min(piece, budget)
                    piece = math.ceil(piece)
                    covered += want
                    if piece <= 0:
                        continue
                    net[(pid, cover)] = net.get((pid, cover), 0) + piece
                    r135_caps.setdefault((pid, cover), headroom)
                    stock_after += piece
                    if budget is not None:
                        budget = max(0.0, budget - piece)
                running_stock[pid] = stock_after
                continue
            # ② 풀 캐퍼로 생산 (생산하는 날은 기계 전체 가동)
            daily_cap = product_daily_cap.get(pid, 0)
            produce = daily_cap if daily_cap > 0 else need
            _logger.info(
                "[순수요] PRODUCE pid=%s %s: current=%.1f req=%.1f "
                "after=%.1f future=%.1f need=%.1f → produce=%.1f (cap=%.1f)",
                pid, date_str, current, required,
                after_consume, future_demand, need, produce, daily_cap,
            )

            # ③ 최대 재고 제한
            if max_inv > 0:
                max_produce = max_inv - after_consume
                produce = min(produce, max_produce)

            # 당일 부족분은 최대 재고보다 우선
            if after_consume < 0:
                produce = max(produce, -after_consume)

            # 사출 생산은 정수 단위 (올림)
            produce = math.ceil(produce)

            net[(pid, date_str)] = produce
            running_stock[pid] = after_consume + produce

        return net

    def _schedule(self, net_demands, config):
        """사출기 배정 + 수량 조정 + 금형 교체 최소화 스케줄링

        금형 교환 최소화 전략:
        1) 각 사출기의 전날 장착 금형(last_mold_id)을 가동일정에서 조회
        2) 작업 순서 결정: 전날 금형과 같은 작업 우선 → 금형별 그룹핑
        3) 그룹 내 작업은 연속 배치하여 교환 없이 처리
        4) 계산 결과만 반환하며 현장 last_mold_id 장착 기록은 변경하지 않음
        """
        Mold = self.env["injection.mold"]
        Avail = self.env["injection.machine.availability"]

        capabilities = self._company_capabilities()
        if not capabilities:
            raise models.UserError(
                "사출기-금형 조합 설정이 없습니다. 먼저 조합을 등록하세요."
            )

        # 제품 → 가능한 조합 매핑 (related 필드 + mold 직접 참조 양쪽 모두)
        product_caps = defaultdict(list)
        for cap in capabilities:
            pid = cap.product_id.id or cap.mold_id.product_id.id
            if pid:
                product_caps[pid].append(cap)
        _logger.info(
            "[스케줄] product_caps 매핑: %s",
            {pid: len(caps) for pid, caps in product_caps.items()},
        )

        # 사출기별 작업 수집 — 배정은 가용시간 헬퍼 정의 후(아래) 수행 [G4/G5]
        machine_jobs = defaultdict(list)

        # 계산 중 '조용한 건너뜀' 을 모으는 자리. 아래 가동 구간 헬퍼도 여기에 적는다.
        _issues = self.env.context.get("plan_issues")

        # 기본 교대 시간 (가동일정 미등록 시 사용)
        # [PR07] 명시적 0 을 `or 8.0` 으로 되살리면 "야간 안 돌린다" 는 설정이
        # 야간 8시간으로 부활한다. 설정 레코드는 항상 존재하므로 값 그대로 쓴다.
        default_day_h = config.day_shift_hours or 0.0
        default_night_h = config.night_shift_hours or 0.0
        # 교대 시작 시각은 injection.planning.config의 단일 설정을 사용한다.
        # 운영 시간이 바뀌면 생산계획 설정의 주간/야간 시작 시각만 수정한다.
        day_start, _night_start = config.get_shift_start_hours()
        day_start_time = config.hour_float_to_time(day_start)
        # `mo_split_mode` 는 더 이상 라인 분할을 좌우하지 않는다. 라인은 **항상**
        # 실제 가동 구간(=교대) 경계에서 끊긴다 — 한 줄이 비가동 시간대를 건너뛰면
        # 그 줄의 시작~종료가 현장에서 성립하지 않기 때문이다. (P1-PP06 B)

        def _get_shift(dt):
            """시간대로 교대 구분"""
            return config.get_shift_code(dt)

        def _get_shift_end(dt, shift):
            """해당 교대의 종료 시각"""
            return config.get_shift_end(dt, shift)

        # 사출기별 가동 일정 조회
        avail_map = {}  # (wc_id, date) → availability record
        avail_records = Avail.search([
            ("date", ">=", str(self.plan_date_from)),
            ("date", "<=", str(self.plan_date_to)),
        ])
        for av in avail_records:
            avail_map[(av.workcenter_id.id, str(av.date))] = av

        # 전날 가동일정에서 사출기별 현재 장착 금형 조회
        prev_date = self.plan_date_from - timedelta(days=1)
        prev_avails = Avail.search([("date", "=", str(prev_date))])
        machine_current_mold = {}
        for av in prev_avails:
            if av.last_mold_id:
                machine_current_mold[av.workcenter_id.id] = av.last_mold_id.id

        def _get_available_hours(wc_id, dt_date):
            """해당 사출기/날짜의 가용 시간"""
            av = avail_map.get((wc_id, str(dt_date)))
            if av:
                dh = av.day_shift_hours or 0.0
                nh = av.night_shift_hours or 0.0
                return dh + nh, dh > 0, nh > 0
            return default_day_h + default_night_h, True, True

        # ── [PP06 B] 가동 시간 구간 ──
        # 예전에는 하루의 주간+야간 시간을 더해 주간 시작부터 **연속으로** 깔았다.
        # 08 시 시작 주간 8h + 20 시 시작 야간 8h 인데 16 시간을 연속 배치하면
        # 16~20 시(비가동)가 작업시간에 들어간다. 교대는 두 개의 끊긴 구간이다.
        night_start_time = config.hour_float_to_time(_night_start)
        machine_windows = {}      # wc_id → [[구간시작, 구간끝], ...] (소비되며 줄어든다)
        machine_pos = {}          # wc_id → 아직 남은 첫 구간의 색인

        def _day_windows(wc_id, dt_date):
            av = avail_map.get((wc_id, str(dt_date)))
            if av:
                dh, nh = av.day_shift_hours or 0.0, av.night_shift_hours or 0.0
            else:
                dh, nh = default_day_h, default_night_h
            out = []
            if dh > 0:
                start = datetime.combine(dt_date, day_start_time)
                out.append([start, start + timedelta(hours=dh)])
            if nh > 0:
                start = datetime.combine(dt_date, night_start_time)
                out.append([start, start + timedelta(hours=nh)])
            out.sort(key=lambda w: w[0])
            return out

        def _merge_windows(wins):
            """겹치는 구간을 합집합으로 만든다. **맞닿기만 한 구간은 합치지 않는다.**

            [PR04] 주간 08시+16h(=~24시)와 야간 20시+8h 를 따로 소비하면 20~24시를
            두 번 쓴 것으로 계산해, 같은 호기에 겹치는 라인이 생긴다. 야간 구간은
            다음 날로 넘어가므로 날짜 안에서만 보면 안 되고 전체를 한 번에 훑는다.
            맞닿은 구간(주간 08~16, 야간 16~24)까지 합치면 교대 구분이 사라지므로
            겹칠 때만 합친다.
            """
            merged = []
            overlapped = False
            for start, end in sorted((list(w) for w in wins), key=lambda w: (w[0], w[1])):
                if merged and start < merged[-1][1]:
                    overlapped = True
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            return merged, overlapped

        shift_tz = pytz.timezone(config.get_shift_timezone())

        def _to_local(aware_dt):
            return aware_dt.astimezone(shift_tz).replace(tzinfo=None)

        def _calendar_windows(wc):
            """설비 작업달력이 실제로 허용하는 근무 구간 (현지 naive).

            달력이 없으면 `None` — **제약을 새로 만들지 않는다.** 연속 가동으로 설정된
            호기에 임의로 점심 휴게를 넣지 않는다는 뜻이다.
            (아스트라 2026-09-10 19:51)
            """
            calendar = wc.resource_calendar_id
            resource = wc.resource_id
            if not calendar or not resource:
                return None
            begin = shift_tz.localize(
                datetime.combine(self.plan_date_from, datetime_time.min))
            finish = shift_tz.localize(
                datetime.combine(self.plan_date_to + timedelta(days=2), datetime_time.min))
            batch = calendar._work_intervals_batch(begin, finish, resources=resource)
            spans = [[_to_local(start), _to_local(stop)]
                     for start, stop, _meta in batch[resource.id]]
            return _merge_windows(spans)[0]

        # 검색 하한은 **현지 자정을 UTC 로 바꾼 값**이어야 한다. 현지 자정을 그대로
        # 넘기면 KST(UTC+9)에서는 9시간 어긋나, 계획 첫날 새벽에 걸친 예약을 놓친다.
        horizon_start = config.shift_local_to_utc(
            datetime.combine(self.plan_date_from, datetime_time.min))

        def _reserved_windows(wc_id=None, mold_id=None):
            """설비 또는 물리 금형이 이미 예약된 시간 (현지 naive).

            둘을 함께 본다.
              1) 작업지시(`mrp.workorder`) — 라우팅이 있는 MO 가 만든 실제 예약
              2) **다른 계획의 확정 라인** — 라우팅 없는 MO 는 작업지시를 만들지 않아
                 1) 로는 보이지 않는다. 그러면 다른 계획이 이미 잡아 둔 시간을 비어
                 있다고 보고 같은 창을 두 번 쓴다. (아스트라 배정 — 다른 계획 예약 대조)

            초안·검토 중인 남의 계획은 빼지 않는다 — 아직 실행이 아니고, 그것까지
            막으면 여러 안을 세워 보는 일이 불가능해진다.
            """
            spans = []
            WorkOrder = self.env.get("mrp.workorder")
            line_resource = ("mold_id", "=", mold_id) if mold_id else ("workcenter_id", "=", wc_id)
            wo_resource = [("workcenter_id", "=", wc_id)] if wc_id else []
            if mold_id and "actual_mold_id" in self.env["mrp.production"]._fields:
                wo_resource = [("production_id.actual_mold_id", "=", mold_id)]
            if WorkOrder is not None and wo_resource:
                for order in WorkOrder.search(wo_resource + [
                    ("state", "not in", ("done", "cancel")),
                    ("date_start", "!=", False),
                    ("date_finished", "!=", False),
                    ("date_finished", ">=", horizon_start),
                ]):
                    spans.append(
                        [config.utc_to_shift_local(order.date_start).replace(tzinfo=None),
                         config.utc_to_shift_local(order.date_finished).replace(tzinfo=None)])

            committed = self.env["injection.planning.line"].search([
                line_resource,
                ("planning_run_id", "!=", self.id),
                ("state", "in", ("confirmed", "done")),
                ("mo_id", "!=", False),
                ("mo_id.state", "not in", ("done", "cancel")),
                ("start_time", "!=", False),
                ("end_time", "!=", False),
                ("end_time", ">=", horizon_start),
            ])
            for line in committed:
                # **교체만 한 앞 구간도 설비 점유다.** `occupancy_start_time` 이
                # 있으면 그때부터 잡힌 것으로 본다(없으면 종전대로 생산 시작).
                occupied_from = line.occupancy_start_time or line.start_time
                spans.append(
                    [config.utc_to_shift_local(occupied_from).replace(tzinfo=None),
                     config.utc_to_shift_local(line.end_time).replace(tzinfo=None)])
            return _merge_windows(spans)[0]

        mold_reserved = {}

        def _mold_reserved_windows(mold_id):
            if mold_id not in mold_reserved:
                spans = list(_reserved_windows(mold_id=mold_id))
                extra = (self.env.context.get("r135_extra_mold_busy") or {}).get(mold_id)
                if extra:
                    spans = _merge_windows(spans + [list(w) for w in extra])[0]
                mold_reserved[mold_id] = spans
            return mold_reserved[mold_id]

        def _intersect_per_day(windows, allowed, wc):
            """교대 구간을 설비 달력과 **하루 단위로** 교차시킨다.

            달력이 그날 아무 근무도 말하지 않으면(예: 주말인데 가동일정에는 근무로
            등록된 날) 그 날은 **가동일정을 그대로 믿는다.** 현장이 명시적으로 '이 날
            돌린다' 고 적어 둔 것을 회사 기본 달력이 조용히 취소하면 안 된다.
            대신 어긋난 사실을 경고로 남긴다.
            """
            if allowed is None:
                return windows
            out = []
            for window in windows:
                same_day = [a for a in allowed
                            if a[1] > window[0] and a[0] < window[1]]
                if not same_day:
                    # [445 계획 리뷰 (3)] 되돌림은 **사람이 그 날짜에 가동일정을 적어 둔
                    # 경우에만** 한다. 가동일정이 없어 설정 기본값으로 만든 창까지
                    # 되살리면, 회사 달력이 쉬는 날에도 기본 야간이 살아난다.
                    if avail_map.get((wc.id, str(window[0].date()))):
                        out.append(list(window))
                        if _issues is not None:
                            _issues.append(
                                "가동일정은 근무인데 설비 달력에는 근무가 없습니다(가동일정을 "
                                "따랐습니다): %s %s"
                                % (wc.name, window[0].strftime("%Y-%m-%d %H:%M")))
                    elif _issues is not None:
                        _issues.append(
                            "설비 달력에 근무가 없어 제외했습니다(가동일정 미등록): %s %s"
                            % (wc.name, window[0].strftime("%Y-%m-%d %H:%M")))
                    continue
                out.extend(_intersect([window], same_day))
            return sorted(out, key=lambda w: w[0])

        def _intersect(windows, allowed):
            if allowed is None:
                return windows
            out = []
            for begin, finish in windows:
                for other_begin, other_finish in allowed:
                    low, high = max(begin, other_begin), min(finish, other_finish)
                    if (high - low).total_seconds() > 60:   # 1분 미만 조각은 버린다
                        out.append([low, high])
            return sorted(out, key=lambda w: w[0])

        def _subtract(windows, busy):
            out = [list(w) for w in windows]
            for busy_begin, busy_end in busy:
                nxt = []
                for begin, finish in out:
                    if busy_end <= begin or busy_begin >= finish:
                        nxt.append([begin, finish])
                        continue
                    if begin < busy_begin:
                        nxt.append([begin, busy_begin])
                    if busy_end < finish:
                        nxt.append([busy_end, finish])
                out = nxt
            return [w for w in out if (w[1] - w[0]).total_seconds() > 60]

        def _windows(wc_id):
            """계획 기간의 가동 구간 전체. 없으면 빈 목록 — 전 기간 휴무다.

            교대 설정에서 만든 구간을 **설비 작업달력**과 교차시키고, **이미 예약된
            작업**을 뺀다. 그래야 계획이 내놓는 시각이 MO 의 예정 시각과 어긋나지 않는다.
            """
            if wc_id not in machine_windows:
                wins = []
                day = self.plan_date_from
                while day <= self.plan_date_to:
                    wins.extend(_day_windows(wc_id, day))
                    day += timedelta(days=1)
                merged, overlapped = _merge_windows(wins)
                wc = self.env["mrp.workcenter"].browse(wc_id)
                if overlapped and _issues is not None:
                    _issues.append(
                        "가동시간 중복(합집합으로 계산): %s — 교대 시작·시간을 확인하십시오."
                        % wc.name)
                allowed = _calendar_windows(wc)
                narrowed = _intersect_per_day(merged, allowed, wc)
                if allowed is not None and _issues is not None:
                    shift_h = sum((w[1] - w[0]).total_seconds() for w in merged) / 3600.0
                    real_h = sum((w[1] - w[0]).total_seconds() for w in narrowed) / 3600.0
                    if shift_h - real_h > 0.01:
                        _issues.append(
                            "설비 작업달력이 교대 설정보다 좁습니다: %s — 교대 %.1fh 중 "
                            "%.1fh 만 가동 가능(휴게·휴무 반영)."
                            % (wc.name, shift_h, real_h))
                busy = _reserved_windows(wc_id)
                extra = (self.env.context.get("r135_extra_busy") or {}).get(wc_id)
                if extra:
                    busy = _merge_windows(list(busy) + [list(w) for w in extra])[0]
                if busy:
                    free = _subtract(narrowed, busy)
                    if _issues is not None and len(free) != len(narrowed):
                        _issues.append(
                            "이미 예약된 작업을 뺀 가동시간으로 계산했습니다: %s" % wc.name)
                    narrowed = free
                if self.schedule_not_before:
                    cutoff = config.utc_to_shift_local(self.schedule_not_before).replace(tzinfo=None)
                    narrowed = [[max(begin, cutoff), finish]
                                for begin, finish in narrowed if finish > cutoff]
                machine_windows[wc_id] = [list(w) for w in narrowed]
            return machine_windows[wc_id]

        def _free_hours(wc_id, mold_id=None, since=None, until=None):
            """아직 소비되지 않은 가동 시간의 합.

            [아스트라 20260912 08:25] 「`_free_hours(since=필요일 00시)` 는 필요일
            이후부터 **계획기간 끝까지**의 시간을 셉니다. 따라서 중간 필요일 당일에는
            2시간밖에 없고 작업은 8시간인데 **다음날 이후** 가용시간이 충분하면
            '조기생산 불필요'로 판단하여 **need_date 다음날에 생산을 끝낼 수**
            있습니다. … **가용성 평가는 수요 납기 상한까지의 윈도여야** 하고 …」

            그래서 `until`(납기 상한)을 받는다. 주지 않으면 종전과 같다.
            """
            wins = _windows(wc_id)[machine_pos.get(wc_id, 0):]
            if mold_id:
                busy = _mold_reserved_windows(mold_id)
                if busy:
                    wins = _subtract(wins, busy)
            total = 0.0
            for start, end in wins:
                if since is not None:
                    if end <= since:
                        continue
                    start = max(start, since)
                if until is not None:
                    if start >= until:
                        continue
                    end = min(end, until)
                if end <= start:
                    continue
                total += (end - start).total_seconds() / 3600.0
            return total

        def _take_job(wc_id, quantity, rate, setup_hours, mold_id,
                      not_before=None, until=None, consume=True):
            """Allocate setup and complete pieces inside each usable window.

            Fractional tails separated by downtime cannot make one piece. Keep
            exact allocated quantities alongside second-rounded timestamps; do
            not infer quantities back from those timestamps. A dry run uses the
            same allocation rules to decide whether the due date needs an early
            start, without consuming machine capacity or advancing its cursor.
            """
            if rate <= 0:
                return [], setup_hours
            source = _windows(wc_id)
            wins = source if consume else [list(window) for window in source]
            entry_index = machine_pos.get(wc_id, 0)
            index = entry_index
            segments = []
            remaining_qty = quantity
            setup_left = setup_hours
            mold_busy = _mold_reserved_windows(mold_id)
            while (remaining_qty > 0 or setup_left > 1e-9) and index < len(wins):
                window_start, window_end = wins[index]
                if not_before is not None:
                    window_start = max(window_start, not_before)
                if until is not None:
                    window_end = min(window_end, until)
                if window_end <= window_start:
                    index += 1
                    continue
                free_windows = (_subtract([[window_start, window_end]], mold_busy)
                                if mold_busy else [[window_start, window_end]])
                allocation = None
                for start, end in free_windows:
                    free = (end - start).total_seconds() / 3600.0
                    used_setup = min(free, setup_left)
                    piece_capacity = math.floor(max(0.0, free - used_setup) * rate + 1e-6)
                    qty = min(remaining_qty, piece_capacity)
                    used = used_setup + qty / rate
                    if used > 1e-9:
                        allocation = (start, end, used_setup, qty, used)
                        break
                if allocation is None:
                    index += 1
                    continue
                start, end, used_setup, qty, used = allocation
                stop = min(start + timedelta(seconds=round(used * 3600.0)), end)
                segments.append((start, stop, qty / rate, used_setup, qty))
                wins[index][0] = stop
                remaining_qty -= qty
                setup_left -= used_setup
                if (window_end - stop).total_seconds() <= 1e-9:
                    index += 1
            if consume:
                # Future-dated jobs must not discard earlier skipped windows.
                machine_pos[wc_id] = entry_index if not_before is not None else index
            return segments, setup_left + remaining_qty / rate

        def _order_mold_groups(jobs_by_mold, prev_mold_id):
            """금형 그룹의 처리 순서.

            [PR05] **적기납품이 최상위 목표다.** 예전에는 전날 금형 다음으로 작업량이
            많은 그룹을 먼저 놓았다. 그래서 오늘 필요한 100개가, 이틀 뒤 필요한 900개
            뒤로 밀려 하루 늦게 끝났다 — 둘 다 기한 안에 넣을 수 있는 입력인데도.

            그래서 **가장 이른 필요일**을 먼저 본다. 금형 교체 최소화(전날 금형 우선)와
            큰 작업 우선은 필요일이 같을 때의 기준으로 내린다.
            """
            ranked = []
            for mold_id, mold_jobs in jobs_by_mold.items():
                earliest = min(j["date_str"] for j in mold_jobs)
                total = sum(j["demand_qty"] for j in mold_jobs)
                ranked.append((
                    earliest,                                  # ① 이른 납기 먼저
                    0 if mold_id == prev_mold_id else 1,       # ② 교체 없는 쪽
                    -total,                                    # ③ 큰 작업 먼저
                    mold_id, mold_jobs,
                ))
            ranked.sort(key=lambda row: row[:3])
            return [(row[3], row[4]) for row in ranked]

        # ── 작업 배정 [G5 형체력 적합성 + G4 유효능력·부하분산·병렬] ──
        assigned_hours = defaultdict(float)  # (wc_id, date_str) → 배정된 시간

        def _eff_cap(c):
            dr = c.defect_rate or 0.0   # 조합에 적힌 값이 정본(0 은 0)
            return c.hourly_capacity * max(0.0, 1.0 - dr / 100.0)

        # 배정 표시(`current_stock`)도 다른 화면과 **같은 범위**를 쓴다. 라인마다 다시
        # 조회하면 느리기만 하고 값도 흔들린다. 한 번 읽어 나눠 쓴다.
        scheduling_on_hand = self._stock_on_hand(
            self.env["product.product"].browse(
                sorted({pid for pid, _date in net_demands.keys()})))

        unassigned = []          # [PP06] 물리 제약에 걸려 배정하지 못한 수요

        def _drop(pid, date_str, qty, reason, detail):
            """배정 못 한 수요를 미배정 큐로 보낸다. 조용히 사라지지 않게."""
            unassigned.append({
                "planning_run_id": self.id, "product_id": pid,
                "plan_date": date_str, "qty": qty,
                "reason": reason, "detail": detail,
            })
            if _issues is not None:
                _p = self.env["product.product"].browse(pid)
                _issues.append("미배정(%s): %s %s %.0f개 — %s"
                               % (reason, _p.default_code or _p.name, date_str, qty, detail))

        unverified = {}          # cap.id → 확인하지 못한 이유 (0 은 '부족' 이 아니다)

        def _usable_caps(caps_list):
            """[PP06 A] 물리 제약 하드 필터.

            예전에는 형체력 적합 후보가 하나도 없으면 **경고만 남기고 부적합 후보를
            그대로 돌려줬다**. 안전·물리 제약을 경고로 낮추면 계획은 늘 성립하지만
            현장에서 그 금형은 그 호기에 올라가지 않는다. 여기서는 차단한다.

            형체력이 **등록되지 않은**(0) 경우는 여전히 통과시킨다 — 미등록을 '부족'
            으로 읽으면 마스터를 채우기 전까지 전 품목이 미배정으로 떨어진다. 대신
            그 사실을 경고로 남긴다.
            """
            ok, blocked = [], {}
            for cap in caps_list:
                mold = cap.mold_id
                if not mold.active or mold.state != "active":
                    blocked.setdefault("mold_state", []).append(
                        "%s(%s)" % (mold.display_name or mold.code,
                                    dict(mold._fields["state"].selection).get(mold.state)
                                    if mold.active else "보관 해제"))
                    continue
                need = mold.required_clamping_ton or 0.0
                have = cap.workcenter_id.x_clamping_force_ton or 0.0
                if need and have and have + 1e-6 < need:
                    blocked.setdefault("clamping", []).append(
                        "%s(요구 %.0ft) > %s(%.0ft)"
                        % (mold.display_name or mold.code, need,
                           cap.workcenter_id.name, have))
                    continue
                if need and not have:
                    # 0 은 '부족' 이 아니라 '확인되지 않음' 이다. 후보에서 빼지 않되
                    # 이 사실을 라인에 달아 확정·MO 생성에서 막는다. (아스트라 2026-09-10 18:41)
                    unverified[cap.id] = _(
                        "사출기 %(machine)s 의 형체력이 등록되지 않아 금형 %(mold)s 의 "
                        "요구 %(need).0f톤을 만족하는지 확인할 수 없습니다.",
                        machine=cap.workcenter_id.name,
                        mold=mold.display_name or mold.code, need=need)
                    if _issues is not None:
                        _issues.append("적합성 미확인(확정 차단): %s" % unverified[cap.id])
                ok.append(cap)
            return ok, blocked

        # [PP06 C] 실물 금형 하나는 이 계획 기간 동안 **한 사출기에만** 올린다.
        # 예전에는 같은 mold_id 가 여러 호기 capability 에 있으면 같은 날 병렬로
        # 나눠 배정했다 — 금형은 하나뿐인데 두 대에서 동시에 돌아가는 계획이 된다.
        # (제품이 같아도 금형이 다르면 여전히 병렬로 나뉜다.)
        mold_machine = {}

        def _pin_rank(cap):
            """고정 후보의 우열. **쓸 수 있는 호기가 먼저**, 그다음 유효능력.

            [PR03] 예전에는 가동시간을 보지 않고 유효능력이 가장 높은 호기에 기간 전체를
            고정했다. 그 호기가 계획 기간 내내 휴무면, 하루 240개를 낼 수 있는 차선
            호기를 두고도 수요 전량이 미배정으로 떨어졌다.
            """
            return (_free_hours(cap.workcenter_id.id, cap.mold_id.id) > 0.0, _eff_cap(cap))

        def _pin(caps_list):
            """금형별로 딱 한 조합만 남긴다. 처음 쓰는 금형은 실제로 돌릴 수 있는 호기에."""
            picked = []
            for cap in sorted(caps_list, key=_pin_rank, reverse=True):
                mold_id = cap.mold_id.id
                chosen = mold_machine.get(mold_id)
                if chosen is None:
                    chosen = max(
                        (c for c in caps_list if c.mold_id.id == mold_id),
                        key=_pin_rank)
                    mold_machine[mold_id] = chosen
                if chosen in caps_list and chosen not in picked:
                    picked.append(chosen)
            return picked

        manual_jobs = self.env.context.get("r135_manual_jobs")
        if manual_jobs is not None:
            helpers = {"take_job": _take_job, "drop": _drop, "unverified": unverified, "get_shift": _get_shift,
                       "current_mold": machine_current_mold, "capabilities": capabilities,
                       "unassigned_list": unassigned}
            return self._r135_place_manual(manual_jobs, helpers, config)
        if config.sequencing_mode == "setup_aware":
            helpers = {
                "windows": _windows, "free_hours": _free_hours, "take_job": _take_job,
                "usable_caps": _usable_caps, "drop": _drop, "unverified": unverified,
                "mold_busy": _mold_reserved_windows, "get_shift": _get_shift,
                "machine_windows": machine_windows, "machine_pos": machine_pos, "mold_reserved": mold_reserved,
                "on_hand": scheduling_on_hand, "current_mold": machine_current_mold,
                "unassigned_list": unassigned,
            }
            return self._r135_sequence(net_demands, product_caps, helpers, config)

        for (pid, date_str), demand_qty in sorted(
            net_demands.items(), key=lambda x: (x[0][1], -x[1])  # [G3] 납기순, 동일일자 수량 큰 순
        ):
            caps = product_caps.get(pid, [])
            if not caps:
                _logger.warning("제품 ID %s에 대한 사출기-금형 조합 없음, 건너뜀", pid)
                _drop(pid, date_str, demand_qty, "no_capability",
                      "이 부품을 만들 수 있는 사출기-금형 조합이 등록되어 있지 않다")
                continue

            usable, blocked = _usable_caps(caps)
            if not usable:
                reason = "clamping" if blocked.get("clamping") else "mold_state"
                _drop(pid, date_str, demand_qty, reason,
                      "; ".join(blocked.get(reason, []))[:200])
                continue

            # [G4] 유효능력(불량률 반영) 높은 순으로 후보 정렬 — 단, 금형당 한 호기
            ranked = sorted(_pin(usable), key=_pin_rank, reverse=True)
            remaining_qty = demand_qty
            for cap in ranked:
                if remaining_qty <= 0:
                    break
                wc = cap.workcenter_id.id
                eff = _eff_cap(cap) or (cap.hourly_capacity or 1.0)
                if cap is ranked[-1]:
                    take = remaining_qty  # 마지막 후보: 잔량 전부(초과분은 가동 구간이 이월)
                else:
                    # [G4 부하분산] 이 기계의 당일 잔여 가용시간만큼만 → 넘치면 차선 기계로(병렬)
                    avail_h, _d, _n2 = _get_available_hours(wc, date_str)
                    free_h = min(avail_h - assigned_hours[(wc, date_str)],
                                 _free_hours(wc, cap.mold_id.id))
                    if free_h <= 0.1:
                        continue
                    cap_qty = int(free_h * eff)
                    if cap_qty <= 0:
                        continue
                    take = min(remaining_qty, cap_qty)
                machine_jobs[wc].append({
                    "product_id": pid,
                    "date_str": date_str,
                    "demand_qty": take,
                    "capability": cap,
                })
                assigned_hours[(wc, date_str)] += (take / eff) if eff > 0 else 0.0
                remaining_qty -= take

        # 사출기별 스케줄링
        lines_data = []
        total_changeovers = 0

        for wc_id, jobs in machine_jobs.items():
            # 금형별로 그룹핑
            jobs_by_mold = defaultdict(list)
            for job in jobs:
                jobs_by_mold[job["capability"].mold_id.id].append(job)

            # 전날 장착 금형 기반 정렬 (교환 최소화)
            prev_mold_id = machine_current_mold.get(wc_id)
            ordered_groups = _order_mold_groups(jobs_by_mold, prev_mold_id)

            seq = 10
            for mold_id, mold_jobs in ordered_groups:
                mold = Mold.browse(mold_id)
                # 금형 교환 판단: 현재 장착 금형과 다른 경우
                # [PR06] `prev_mold_id` 가 없다는 것은 '아무것도 안 물려 있다' 가 아니라
                # **무엇이 물려 있는지 모른다** 는 뜻이다. 그걸 '이미 이 금형이 장착돼
                # 있다'(교체 0h)로 읽으면, 설치 2시간이 계획에서 통째로 사라진다.
                changeover = prev_mold_id != mold_id
                # [R135 기준 1] 적용한 교체시간의 **출처**를 라인에 남긴다. 값은 바꾸지 않는다.
                mount_unknown = prev_mold_id is None
                if not changeover:
                    changeover_source = "none_same_mold"
                elif mold.changeover_hours_confirmed:
                    changeover_source = "mold_confirmed"
                else:
                    changeover_source = "mold_unconfirmed"
                if changeover:
                    total_changeovers += 1
                # 이 그룹 처리 후 현재 금형 업데이트
                prev_mold_id = mold_id

                # 금형 그룹 내 작업을 날짜순 정렬
                mold_jobs.sort(key=lambda j: j["date_str"])

                for i, job in enumerate(mold_jobs):
                    cap = job["capability"]
                    demand = job["demand_qty"]

                    # 불량율 반영
                    # [PR07 확장] 조합·금형에 적힌 값을 설정 기본값으로 되살리지 않는다.
                    # 불량률 0%·초기불량 0개·교체 0시간은 모두 유효한 입력이다.
                    dr = cap.defect_rate or 0.0
                    adjusted = (
                        math.ceil(demand / (1 - dr / 100.0))
                        if dr < 100
                        else demand
                    )

                    # 초기 불량 (그룹 첫 작업 + 금형 교환 시)
                    needs_changeover = changeover and i == 0
                    scrap = (cap.initial_scrap or 0) if needs_changeover else 0
                    adjusted += scrap

                    # 최소 로트
                    product = self.env["product.product"].browse(
                        job["product_id"]
                    )
                    min_lot = (
                        product.min_lot_size or config.default_min_lot_size
                    )
                    if min_lot > 0 and adjusted < min_lot:
                        adjusted = min_lot

                    co_hours = (mold.changeover_hours or 0.0) if needs_changeover else 0.0

                    # 생산 시간
                    rate = cap.hourly_capacity or 0.0
                    prod_hours = adjusted / rate if rate > 0 else 0.0
                    total_job_hours = co_hours + prod_hours

                    # ── [PP06 B/E] 실제 가동 구간에만 배치한다 ──
                    # 예전에는 "남은 시간이 부족하면 다음 날로 옮겨 통째로 붙인다" 였다.
                    # 그래서 10 시간짜리 작업이 8 시간 가동일에 연속으로 들어갔고,
                    # 계획 기간에 가용일이 없으면 원래 날짜를 그대로 썼다. 지금은
                    # 허용된 구간을 앞에서부터 채우고, 못 채운 만큼은 미배정으로 보낸다.
                    # ── 재고를 고려한 배치 (설정으로 켠다) ──
                    # [아스트라 20260912 08:09] 「같은 max8/5·수요·능력·금형·교체
                    # 시간으로 **미래분을 불필요하게 첫날 전량 생산하지 않도록**
                    # 일정 배치를 보완하십시오. … 납기와 설비/금형 능력은 유지,
                    # **상한 올리기/need_date 를 가짜 완료일로 쓰기** 금지.
                    # 납기를 위해 조기생산이 불가피하면 **초과량·일자·사유를 명시**
                    # 하는 반례도 필요합니다.」
                    #
                    # 필요일보다 이른 구간을 쓰지 않는다. 그렇게 하면 납기를 못
                    # 맞추는 경우에만 당기고, **당긴 사실과 사유를 남긴다.**
                    not_before = due_end = need_start = None
                    if config.inventory_aware_scheduling:
                        # [아스트라 c8a262261b2] 「**Asia/Seoul 시간축 혼용** …
                        # UTC 로 바꾼 경계를 local naive 윈도와 비교하지 않기」
                        #
                        # 가동 구간(`_windows`)은 **교대 기준 현지 naive** 입니다 —
                        # 저장할 때만 `shift_local_to_utc` 로 바꿉니다(:1689).
                        # 앞 판은 경계를 UTC 로 만들어 비교해 **9시간 어긋났습니다.**
                        # 경계도 같은 현지 naive 축으로 만듭니다.
                        need_date = fields.Date.to_date(job["date_str"])
                        # [아스트라 09:01] 「`not_before=None` 으로 풀어둔 뒤
                        # `span_start >= not_before` … 를 호출합니다. **날짜와 None
                        # 비교이므로 TypeError 경로**입니다. 필요일 경계
                        # `need_start` 는 **별도 불변값**으로 두고 `_take_job` 의
                        # **배치제약 해제값과 구분**하십시오.」
                        #
                        # 맞습니다. 같은 변수를 「필요일 경계」와 「배치 제약」 두
                        # 뜻으로 썼습니다. 경계는 절대 None 이 되지 않게 나눕니다.
                        need_start = datetime.combine(need_date, datetime_time.min)
                        not_before = need_start
                        # **납기 상한**까지만 센다. 회사 intraday 마감이 없으므로
                        # 「그 필요일 업무 종료」를 상한으로 명시해 쓴다.
                        due_end = datetime.combine(need_date, datetime_time.max)
                        # **소비하기 전에** 판단한다. `_take_job` 는 가동 구간을
                        # 실제로 깎으므로 두 번 부르면 같은 구간을 두 번 먹는다.
                        free_within = _free_hours(wc_id, mold_id,
                                                  since=not_before, until=due_end)
                        _preview, due_shortfall = _take_job(
                            wc_id, adjusted, rate, co_hours, mold_id,
                            not_before=not_before, until=due_end, consume=False)
                        # 왜 당겼는지/안 당겼는지는 운영에서도 알아야 한다.
                        _logger.info(
                            "[선행배치] %s 필요일 %s: 필요일내 가용 %.2fh / 총 %.2fh"
                            " (교체 %.2fh + 생산 %.2fh) → %s",
                            product.display_name, job["date_str"], free_within,
                            total_job_hours, co_hours, prod_hours,
                            "당김" if due_shortfall > 1e-9
                            else "필요일 이후 배치")
                        if due_shortfall > 1e-9:
                            not_before = None       # 납기를 지키려면 당겨야 한다
                    segments, shortfall = _take_job(
                        wc_id, adjusted, rate, co_hours, mold_id, not_before=not_before)
                    produce_spans = [
                        (start + timedelta(hours=co), end)
                        for start, end, _prod_h, co, qty in segments if qty > 0]

                    if config.inventory_aware_scheduling and need_start is not None:
                        # [아스트라 c8a262261b2] 「**교체시간을 조기 제품수량으로
                        # 세는** … 실제 생산 segments 에서 **교체시간 차감 후** 조기
                        # 수량 집계」
                        #
                        # 앞 판은 배치 구간 전체를 세어 **교체시간까지 제품 수량으로**
                        # 환산했습니다. 교체는 생산이 아닙니다.
                        early_h = 0.0
                        for span_start, span_end in produce_spans:
                            # **`need_start`** 로 센다. `not_before` 는 위에서 풀릴
                            # 수 있는 **배치 제약**이라 경계로 쓰면 안 된다.
                            if span_start >= need_start:
                                continue
                            early_h += (min(span_end, need_start)
                                        - span_start).total_seconds() / 3600.0
                        late = bool(segments) and segments[-1][1] > due_end
                        plan_issues = self.env.context.get("plan_issues")
                        if (late or shortfall > 1e-9) and plan_issues is not None:
                            # **납기 실패를 조기 생산 성공으로 적지 않는다.**
                            plan_issues.append(
                                "납기 미달: %s 필요일 %s — 가동시간이 모자라 "
                                "필요일 안에 끝내지 못했습니다(미배치 %.2fh)"
                                % (product.display_name, job["date_str"],
                                   shortfall))
                        elif early_h > 1e-9 and plan_issues is not None:
                            plan_issues.append(
                                "납기 준수를 위한 조기 생산: %s 필요일 %s — "
                                "앞 구간에서 생산 %.2fh(약 %.0f개, 교체시간 제외)를 "
                                "미리 만들었습니다"
                                % (product.display_name, job["date_str"],
                                   early_h, early_h * rate))

                    placed_qty_total = 0
                    placeable = sum(qty for _s, _e, _h, _co, qty in segments)

                    if placeable < adjusted:
                        # 계획 기간 안에 다 넣지 못했다 — 전 기간 휴무면 placed 가 비어
                        # placeable 이 0 이고, 수요 전량이 미배정으로 간다. (시험 ⑤)
                        _drop(job["product_id"], job["date_str"],
                              adjusted - placeable, "no_capacity",
                              "%s 의 계획 기간 가동 구간이 %.1fh 부족하다"
                              % (cap.workcenter_id.name, shortfall))
                        if placeable <= 0:
                            continue

                    # 구간마다 한 줄. 한 줄이 비가동 시간대를 건너뛰지 않게 한다.
                    remaining_qty = placeable
                    remaining_demand = demand
                    is_first = True
                    # [아스트라 20260912-01 #2] 「**교체 전용 시간을 실제 설비·금형·
                    # 회사·시간대와 함께 보존**하고 확정 계획의 **예약 조회에서
                    # 누락되지 않도록** 합니다.」
                    #
                    # 생산량이 0 인 구간(=교체만 한 구간)은 계획 라인을 만들지 않아
                    # **그 시간이 어디에도 남지 않았습니다.** 그래서 다른 계획이 같은
                    # 창을 다시 예약했습니다(대조군으로 확인). 건너뛴 구간의 시작을
                    # 들고 있다가 **첫 생산 라인의 점유 시작**으로 남깁니다.
                    held_occupancy_start = None
                    for seg_start, seg_end, prod_h, seg_co, seg_qty in segments:
                        if remaining_qty <= 0:
                            break
                        if seg_qty <= 0:
                            if held_occupancy_start is None:
                                held_occupancy_start = seg_start
                            continue
                        seg_demand = (round(remaining_demand * seg_qty / remaining_qty, 2)
                                      if remaining_qty > 0 else 0.0)
                        lines_data.append({
                            "planning_run_id": self.id,
                            "sequence": seq,
                            "plan_date": job["date_str"],
                            "workcenter_id": wc_id,
                            "mold_id": mold_id,
                            "product_id": job["product_id"],
                            "demand_qty": seg_demand,
                            "planned_qty": seg_qty,
                            "defect_rate": dr,
                            "initial_scrap": scrap if is_first else 0,
                            "changeover_needed": needs_changeover if is_first else False,
                            "changeover_hours": co_hours if is_first else 0.0,
                            # **이 구간 안에서 실제로 쓴** 교체시간. 전날 창에서
                            # 소진된 교체는 여기 0 이다 — MO 소요 계산이 교체를
                            # 다시 더하지 않게 하는 원천이다.
                            "changeover_in_span_hours": seg_co,
                            "changeover_source": changeover_source if is_first else "none_same_mold",
                            "mount_unknown": mount_unknown if is_first else False,
                            # 교체만 한 앞 구간이 있으면 **그때부터 설비를 잡고**
                            # 있었다. 예약 조회가 그 시간을 보게 한다.
                            "occupancy_start_time": (
                                config.shift_local_to_utc(held_occupancy_start)
                                if held_occupancy_start else False),
                            "start_time": config.shift_local_to_utc(seg_start),
                            # The allocator already stops at setup + whole-piece
                            # duration. Clipping an overloaded last line cannot
                            # make it executable; its excess belongs in a later
                            # window or in unassigned demand.
                            "end_time": config.shift_local_to_utc(seg_end),
                            "shift": _get_shift(seg_start),
                            "fit_unverified": cap.id in unverified,
                            "fit_note": unverified.get(cap.id, False),
                            "current_stock": scheduling_on_hand.get(product.id, 0.0),
                            "max_inventory": product.max_inventory_qty,
                        })
                        held_occupancy_start = None
                        seq += 10
                        remaining_qty -= seg_qty
                        remaining_demand -= seg_demand
                        placed_qty_total += seg_qty
                        is_first = False

        # [PR03] 계획 계산은 실물 장착 이력(`machine_availability.last_mold_id`)을
        # **쓰지 않는다**. 예전에는 계획 종료일 가동일정에 예측 금형을 적었다. 그러면
        # 초안 계산이나 재계산만으로 다음 계획의 시작 금형이 바뀌고, 배정이 0인
        # 계산조차 현장 사실을 거짓 갱신했다. 그 필드의 정본은 현장 기록이다.
        # 이 계획이 예측한 종료 시점 금형은 호기별 마지막 라인이 그대로 말해 준다.

        if total_changeovers:
            _logger.info(
                "스케줄링 완료: 총 금형 교환 %d회", total_changeovers
            )

        return lines_data, unassigned

    # ─────────────────────────────────────────────
    # [R135 §4.2] 교체 인식 순서기 — 유한 능력 위 납기 우선, 재고 범위 안 교체 최소
    # ─────────────────────────────────────────────
    def _r135_setup(self, cap, mold, cur_mold_id):
        """(교체시간, 값 출처, 장착 미확인). 조합 override 는 0 도 확인된 값(검토 #3)."""
        if cur_mold_id == mold.id:
            return 0.0, "none_same_mold", False
        mount_unknown = cur_mold_id is None
        if cap.changeover_override:
            return cap.changeover_hours or 0.0, "capability", mount_unknown
        return (mold.changeover_hours or 0.0,
                "mold_confirmed" if mold.changeover_hours_confirmed else "mold_unconfirmed", mount_unknown)

    def _r135_build_lines(self, lines, segments, placeable, seq, config, h, cap, product, job):
        """배치 구간(segments) → 계획 라인 dict. 교체 전용 앞 구간은 첫 생산 라인의 점유 시작으로 남긴다."""
        remaining, held, is_first = placeable, None, True
        for seg_start, seg_end, _prod_h, seg_co, seg_qty in segments:
            if remaining <= 0:
                break
            if seg_qty <= 0:
                held = held or seg_start
                continue
            lines.append({
                "planning_run_id": self.id, "sequence": seq, "plan_date": job["plan_date"],
                "workcenter_id": job["workcenter_id"], "mold_id": job["mold_id"], "product_id": job["product_id"],
                "demand_qty": round(job["need_good"] * seg_qty / placeable, 2) if placeable else 0.0,
                "planned_qty": seg_qty, "defect_rate": job["defect_rate"],
                "initial_scrap": job["initial_scrap"] if is_first else 0,
                "changeover_needed": job["changeover"] if is_first else False,
                "changeover_hours": job["setup_h"] if is_first else 0.0, "changeover_in_span_hours": seg_co,
                "changeover_source": job["source"] if is_first else "none_same_mold",
                "mount_unknown": job["mount_unknown"] if is_first else False,
                "occupancy_start_time": config.shift_local_to_utc(held) if held else False,
                "start_time": config.shift_local_to_utc(seg_start), "end_time": config.shift_local_to_utc(seg_end),
                "shift": h["get_shift"](seg_start), "fit_unverified": cap.id in h["unverified"],
                "fit_note": h["unverified"].get(cap.id, False),
                "current_stock": job["on_hand"], "max_inventory": product.max_inventory_qty,
            })
            held = None; seq += 10; remaining -= seg_qty; is_first = False
        return seq

    def _r135_place_manual(self, jobs_by_wc, h, config):
        """[R135 검토 #5] 담당자가 정한 순서대로 **실제 시간을 다시 배치**한다. 최적화 없음.

        같은 사출기의 초안 라인을 사용자의 일별 순서대로 앞에서부터 놓고, 금형이 바뀌면 교체를 다시 계산한다.
        확정·MO 라인은 `r135_extra_busy` 로 점유에 넣어 건드리지 않는다. 창·예약·교대 경계는 계산과 같은 클로저다.
        """
        Mold = self.env["injection.mold"]
        cap_of = {(c.workcenter_id.id, c.mold_id.id): c for c in h["capabilities"]}
        on_hand = self._stock_on_hand(self.env["product.product"].browse(
            sorted({j["product_id"] for jobs in jobs_by_wc.values() for j in jobs})))
        lines, issues = [], self.env.context.get("plan_issues")
        for wc in sorted(jobs_by_wc):
            cur, seq = h["current_mold"].get(wc), 10
            for job in jobs_by_wc[wc]:
                cap = cap_of.get((wc, job["mold_id"]))
                mold, product = Mold.browse(job["mold_id"]), self.env["product.product"].browse(job["product_id"])
                if not cap or not cap.hourly_capacity:
                    h["drop"](job["product_id"], job["plan_date"], job["qty"], "no_capability",
                              "이 사출기·금형 조합이 없거나 능력이 0 이다(수동 순서 재배치)")
                    continue
                setup_h, source, mount_unknown = self._r135_setup(cap, mold, cur)
                segments, shortfall = h["take_job"](wc, job["qty"], cap.hourly_capacity, setup_h, mold.id, not_before=None)
                placeable = sum(q for _s, _e, _h, _co, q in segments)
                if placeable < job["qty"]:
                    h["drop"](job["product_id"], job["plan_date"], job["qty"] - placeable, "no_capacity",
                              "수동 순서대로 놓으니 %s 의 가동 구간이 %.1fh 부족하다" % (cap.workcenter_id.name, shortfall))
                    if placeable <= 0:
                        cur = mold.id
                        continue
                seq = self._r135_build_lines(
                    lines, segments, placeable, seq, config, h, cap, product,
                    dict(plan_date=job["plan_date"], workcenter_id=wc, mold_id=mold.id, product_id=job["product_id"],
                         need_good=job["demand_qty"], defect_rate=job["defect_rate"], initial_scrap=job["initial_scrap"],
                         changeover=cur != mold.id, setup_h=setup_h, source=source, mount_unknown=mount_unknown,
                         on_hand=on_hand.get(job["product_id"], 0.0)))
                cur = mold.id
        return lines, h["unassigned_list"]

    def _r135_sequence(self, net_demands, product_caps, h, config):
        """결정적 탐욕 리스트 스케줄링 + 제한 개선 탐색. 휴리스틱이며 전역 최적을 보장하지 않는다.

        우선순위(아스트라 Q2·검토 #1·#2): 물리·예약 제약 → 납기(누적 여력으로 긴급 판정) → 재고 범위 →
        교체 최소(현 금형 유지, 재고 상한·타 긴급 안에서 연장) → 조기생산 최소. 동률은 (납기, 수량 큰 순, id).
        개선 탐색: 하드 위반(지연·미배정)이 남으면 해당 금형의 사출기 고정을 다른 적합 호기로 바꿔
        처음부터 다시 돌린다. 목적 벡터가 엄격히 좋아질 때만 채택, 시도 상한·종료 사유를 기록한다.
        """
        Mold = self.env["injection.mold"]
        caps_ctx = self.env.context.get("r135_caps") or {}
        demand_series = self.env.context.get("r135_demand") or {}          # {pid: {date_str: qty}} — action_calculate_plan 이 넣는다
        stats = self.env.context.get("r135_search_stats")
        if stats is None:
            stats = {}
        max_attempts = 20
        products = {pid: self.env["product.product"].browse(pid) for pid, _d in net_demands}

        def due_end_of(date_str, wc):
            return self._r135_due_end(config, wc, fields.Date.to_date(date_str))

        def adjusted_qty(cap, need_good, first_of_group, product):
            dr = cap.defect_rate or 0.0
            qty = math.ceil(need_good / (1 - dr / 100.0)) if dr < 100 else need_good
            scrap = (cap.initial_scrap or 0) if first_of_group else 0
            qty += scrap
            min_lot = product.min_lot_size or config.default_min_lot_size
            if min_lot > 0 and qty < min_lot:
                qty = min_lot
            return qty, scrap, dr

        def run_once(pin_override):
            """한 번의 탐욕 배치. 창·커서·금형 예약 상태를 비우고 시작한다."""
            h["machine_windows"].clear(); h["machine_pos"].clear(); h["mold_reserved"].clear()
            unassigned, lines, issues = [], [], []
            # 제품별 작업(납기순) — 필요 양품량
            pending = defaultdict(list)
            for (pid, date_str), need in sorted(net_demands.items(), key=lambda x: (x[0][1], x[0][0])):
                pending[pid].append({"date_str": date_str, "need": float(need), "cap": caps_ctx.get((pid, date_str))})
            # 금형→사출기 고정 (탐색이 override 할 수 있다)
            mold_machine, cap_of, blocked_by_pid = {}, {}, {}
            for pid, caps in product_caps.items():
                usable, blocked = h["usable_caps"](caps)
                blocked_by_pid[pid] = blocked
                for cap in usable:
                    mid = cap.mold_id.id
                    if mid in pin_override and cap.workcenter_id.id == pin_override[mid]:
                        mold_machine[mid] = cap.workcenter_id.id; cap_of[mid] = cap
                    elif mid not in pin_override and (mid not in mold_machine or (
                            h["free_hours"](cap.workcenter_id.id, mid), cap.hourly_capacity, -cap.workcenter_id.id)
                            > (h["free_hours"](mold_machine[mid], mid), cap_of[mid].hourly_capacity, -mold_machine[mid])):
                        mold_machine[mid] = cap.workcenter_id.id; cap_of[mid] = cap
            product_molds = defaultdict(list)
            for mid, cap in cap_of.items():
                product_molds[cap.product_id.id or cap.mold_id.product_id.id].append(mid)
            for pid in list(pending):
                if not product_molds.get(pid):
                    blocked = blocked_by_pid.get(pid) or {}
                    if not product_caps.get(pid):
                        reason, detail = "no_capability", "이 부품을 만들 수 있는 사출기-금형 조합이 등록되어 있지 않다"
                    else:                                    # 기존 방식(_usable_caps)과 같은 사유·설명
                        reason = "clamping" if blocked.get("clamping") else "mold_state"
                        detail = "; ".join(blocked.get(reason, []))[:200]
                    for job in pending.pop(pid):
                        unassigned.append({"planning_run_id": self.id, "product_id": pid, "plan_date": job["date_str"],
                                           "qty": job["need"], "reason": reason, "detail": detail})
            cur_mold = dict(h["current_mold"])
            machines = sorted({wc for wc in mold_machine.values()})
            seq_by_wc = defaultdict(lambda: 10)
            changeovers = 0
            # 재고 궤적(예상 양품, 배치일 도착으로 보수적) — 연장 판단용
            stock = {pid: h["on_hand"].get(pid, 0.0) for pid in pending}

            def next_free(wc):
                wins = h["windows"](wc)[h["machine_pos"].get(wc, 0):]
                return wins[0][0] if wins else None

            def work_hours(wc, mid, need_good, first):
                cap = cap_of[mid]; product = products[cap.product_id.id or cap.mold_id.product_id.id]
                qty, _scrap, _dr = adjusted_qty(cap, need_good, first, product)
                return qty / (cap.hourly_capacity or 1.0)

            def mold_jobs(wc):
                out = []
                for mid, m_wc in mold_machine.items():
                    if m_wc != wc:
                        continue
                    pid = cap_of[mid].product_id.id or cap_of[mid].mold_id.product_id.id
                    if pending.get(pid):
                        out.append((mid, pid))
                return out

            while any(pending.values()):
                # 다음 자유 시각이 가장 이른 사출기부터(동률 id)
                choice = None
                for wc in machines:
                    if not mold_jobs(wc):
                        continue
                    nf = next_free(wc)
                    if nf is None:
                        continue
                    if choice is None or (nf, wc) < choice[:2]:
                        choice = (nf, wc)
                if choice is None:
                    _logger.info("[R135 순서] 창 없음 — 남은 작업 %s", {p: [(j["date_str"], j["need"]) for j in js] for p, js in pending.items() if js})
                    break                                       # 남은 작업은 창이 없다
                now, wc = choice
                cands = mold_jobs(wc)
                # ── 긴급 판정: 누적 여력 (검토 #2) — 같은 사출기의 납기순 미결 작업 합
                scored = []
                for mid, pid in cands:
                    job = pending[pid][0]
                    setup_h = self._r135_setup(cap_of[mid], Mold.browse(mid), cur_mold.get(wc))[0]
                    own = setup_h + work_hours(wc, mid, job["need"], True)
                    # [R141 F2] 동률 납기를 '앞 작업' 으로 세고 각각에 교체를 가정하면 없는 긴급이 생긴다.
                    # 엄격히 이른 납기만 세고, 교체는 현재 장착 금형에서 납기순으로 이어서 센다.
                    earlier, chain_cur = 0.0, cur_mold.get(wc)
                    for mid2, pid2 in sorted(cands, key=lambda c: (pending[c[1]][0]["date_str"], c[0])):
                        j2 = pending[pid2][0]
                        if j2["date_str"] >= job["date_str"]:
                            continue
                        earlier += self._r135_setup(cap_of[mid2], Mold.browse(mid2), chain_cur)[0] + work_hours(wc, mid2, j2["need"], True)
                        chain_cur = mid2
                    avail = h["free_hours"](wc, mid, since=now, until=due_end_of(job["date_str"], wc))
                    slack = avail - own - earlier
                    scored.append((slack, job["date_str"], -job["need"], mid, pid))
                urgent = [row for row in scored if row[0] <= 1e-9]
                # [R141 F2] 같은 납기 동률에서는 현 금형이 먼저(납기 → 현 금형 유지 → 수량 → ID). ID 순으로 교체를
                # 만들지 않는다(독립시험 f0: A 장착·A2/B2 동일 납기에서 B 먼저 → 교체 2).
                tie = lambda r: (r[1], 0 if r[3] == cur_mold.get(wc) else 1, r[2], r[3])
                if urgent:
                    urgent.sort(key=tie); mid, pid = urgent[0][3], urgent[0][4]
                elif cur_mold.get(wc) in [m for m, _p in cands] and all(
                        row[0] - (self._r135_setup(cap_of[cur_mold[wc]], Mold.browse(cur_mold[wc]), cur_mold[wc])[0]
                                  + work_hours(wc, cur_mold[wc], pending[next(p for m, p in cands if m == cur_mold[wc])][0]["need"], False))
                        >= -1e-9 for row in scored if row[3] != cur_mold[wc]):
                    mid = cur_mold[wc]; pid = next(p for m, p in cands if m == mid)
                else:
                    scored.sort(key=tie); mid, pid = scored[0][3], scored[0][4]
                cap, mold, product = cap_of[mid], Mold.browse(mid), products[pid]
                setup_h, source, mount_unknown = self._r135_setup(cap, mold, cur_mold.get(wc))
                job = pending[pid].pop(0)
                need_good, due_str, cap_headroom = job["need"], job["date_str"], job["cap"]
                merged = []
                # [PP06 4b 유지] 같은 제품의 다른 금형이 다른 사출기에 고정돼 있으면 병렬로 나눈다:
                # 이 사출기에서 납기까지 들어가는 양품만큼만 놓고 나머지는 같은 납기로 되돌려 그 사출기가 받게 한다.
                siblings = [m for m in product_molds.get(pid, []) if m != mid and mold_machine.get(m) != wc]
                if siblings:
                    fit_h = h["free_hours"](wc, mid, since=now, until=due_end_of(due_str, wc)) - setup_h
                    fit_good = math.floor(max(0.0, fit_h) * (cap.hourly_capacity or 0.0) * max(0.0, 1 - (cap.defect_rate or 0.0) / 100.0) + 1e-6)
                    other_open = any(h["free_hours"](mold_machine[m], m, since=next_free(mold_machine[m]) or now,
                                                     until=due_end_of(due_str, mold_machine[m])) > 0 for m in siblings)
                    _logger.info("[R135 순서] wc=%s mold=%s pid=%s due=%s need=%.0f fit_h=%.2f fit_good=%s other_open=%s",
                                 wc, mid, pid, due_str, need_good, fit_h, fit_good, other_open)
                    if other_open and 0 < fit_good < need_good:
                        # 되돌린 나머지는 아래 연장 루프가 다시 삼키면 안 된다(ac89389 추적: 분할 뒤 재병합으로 5000 통째 배치).
                        pending[pid].insert(0, {"date_str": due_str, "need": need_good - fit_good, "cap": cap_headroom, "split": True})
                        need_good = float(fit_good)
                split_off = bool(siblings)
                # ── 연장 후보 (Q2 · R141 F3): 같은 제품의 다음 필요분을 **별도 후속 작업**으로 이어 붙인다(교체 0).
                #   묶음 하나로 합쳐 첫 납기로 재분류하지 않는다 — 지연은 수요별 원 납기 기준으로 센다.
                #   조건: 형제 금형 없음 · 되돌린 분할분 아님 · 재고 상한 여유 · 다른 후보의 납기 여력 유지 · 후속 작업이 제 납기 안에 들어감.
                followups = []
                if not split_off:
                    planned_h = setup_h + work_hours(wc, mid, need_good, True)
                    while pending[pid]:
                        nxt = pending[pid][0]
                        if nxt.get("split"):
                            break
                        extra_h = work_hours(wc, mid, nxt["need"], False)
                        headroom = nxt["cap"]
                        if headroom is not None and need_good + sum(f["need"] for f in followups) + nxt["need"] > headroom + 1e-6:
                            break
                        if h["free_hours"](wc, mid, since=now, until=due_end_of(nxt["date_str"], wc)) < planned_h + extra_h - 1e-9:
                            break                               # 후속 작업이 제 납기 안에 안 들어간다
                        others_ok = True
                        for mid2, pid2 in cands:
                            if mid2 == mid:
                                continue
                            j2 = pending[pid2][0]
                            need_h = self._r135_setup(cap_of[mid2], Mold.browse(mid2), mid)[0] + work_hours(wc, mid2, j2["need"], True)
                            avail = h["free_hours"](wc, mid2, since=now, until=due_end_of(j2["date_str"], wc))
                            if avail - (planned_h + extra_h) - need_h < -1e-9:
                                others_ok = False; break
                        if not others_ok:
                            break
                        followups.append(pending[pid].pop(0)); planned_h += extra_h
                first = cur_mold.get(wc) != mid
                qty, scrap, dr = adjusted_qty(cap, need_good, first, product)
                rate = cap.hourly_capacity or 0.0
                # [R141 F3 대조군] 상한이 있으면 상한을 넘기는 선행 생산을 하지 않는다: 수요 시계열로 '지금 만들어도
                # 상한 안' 인 첫 날부터 시작한다(그 전엔 설비를 비워 둔다). 수요 시계열이 없으면(직접 _schedule) 적용 안 함.
                not_before = None
                max_inv = product.max_inventory_qty or 0.0
                if max_inv > 0 and demand_series:
                    proj, day = stock.get(pid, 0.0), now.date()
                    while str(day) <= due_str:
                        if proj + self._expected_good(qty, scrap, dr) <= max_inv + 1e-6:
                            break
                        proj -= demand_series.get(pid, {}).get(str(day), 0.0)
                        day += timedelta(days=1)
                    if day > now.date():
                        not_before = datetime.combine(min(day, fields.Date.to_date(due_str)), datetime_time.min)
                segments, shortfall = h["take_job"](wc, qty, rate, setup_h, mid, not_before=not_before)
                placeable = sum(q for _s, _e, _h, _co, q in segments)
                _logger.info("[R135 배치] wc=%s mold=%s pid=%s due=%s qty=%.0f placed=%.0f setup=%.1f first=%s next_free_before=%s",
                             wc, mid, pid, due_str, qty, placeable, setup_h, first, now)
                if first:
                    changeovers += 1
                cur_mold[wc] = mid
                if placeable < qty:
                    unassigned.append({"planning_run_id": self.id, "product_id": pid, "plan_date": due_str,
                                       "qty": qty - placeable, "reason": "no_capacity",
                                       "detail": "%s 의 계획 기간 가동 구간이 %.1fh 부족하다" % (cap.workcenter_id.name, shortfall)})
                    if placeable <= 0:
                        continue
                stock[pid] = stock.get(pid, 0.0) + self._expected_good(placeable, scrap, dr)
                seq_by_wc[wc] = self._r135_build_lines(
                    lines, segments, placeable, seq_by_wc[wc], config, h, cap, product,
                    dict(plan_date=due_str, workcenter_id=wc, mold_id=mid, product_id=pid, need_good=need_good,
                         defect_rate=dr, initial_scrap=scrap, changeover=first, setup_h=setup_h,
                         source=source, mount_unknown=mount_unknown, on_hand=h["on_hand"].get(pid, 0.0)))
                own_end = segments[-1][1] if segments else None
                for f in followups:
                    if own_end is not None and own_end > due_end_of(due_str, wc):
                        pending[pid].insert(0, f); continue        # 본 작업이 제 납기를 넘겼으면 연장하지 않는다
                    fqty, _fs, fdr = adjusted_qty(cap, f["need"], False, product)
                    fseg, fshort = h["take_job"](wc, fqty, rate, 0.0, mid, not_before=None)
                    fplaced = sum(q for _s, _e, _h, _co, q in fseg)
                    _logger.info("[R135 배치] wc=%s mold=%s pid=%s due=%s qty=%.0f placed=%.0f setup=0.0 first=False (연장 후속)",
                                 wc, mid, pid, f["date_str"], fqty, fplaced)
                    if fplaced < fqty:
                        unassigned.append({"planning_run_id": self.id, "product_id": pid, "plan_date": f["date_str"],
                                           "qty": fqty - fplaced, "reason": "no_capacity",
                                           "detail": "%s 의 계획 기간 가동 구간이 %.1fh 부족하다(연장 후속)" % (cap.workcenter_id.name, fshort)})
                    if fplaced > 0:
                        stock[pid] += self._expected_good(fplaced, 0, fdr)
                        seq_by_wc[wc] = self._r135_build_lines(
                            lines, fseg, fplaced, seq_by_wc[wc], config, h, cap, product,
                            dict(plan_date=f["date_str"], workcenter_id=wc, mold_id=mid, product_id=pid, need_good=f["need"],
                                 defect_rate=fdr, initial_scrap=0, changeover=False, setup_h=0.0,
                                 source="none_same_mold", mount_unknown=False, on_hand=h["on_hand"].get(pid, 0.0)))
                        issues.append("연장 생산: %s 필요일 %s 분 %.0f개를 같은 금형으로 이어서 미리 생산(교체 회피; 원 수요일 보존)"
                                      % (product.display_name, f["date_str"], f["need"]))
            for pid, jobs in pending.items():
                for job in jobs:
                    unassigned.append({"planning_run_id": self.id, "product_id": pid, "plan_date": job["date_str"],
                                       "qty": job["need"], "reason": "no_capacity", "detail": "계획 기간에 남은 가동 구간이 없다"})
            return lines, unassigned, changeovers, issues

        def objective(lines, unassigned):
            late = sum(l["planned_qty"] for l in lines
                       if config.utc_to_shift_local(l["end_time"]).date() > fields.Date.to_date(l["plan_date"]))
            early = sum(l["planned_qty"] for l in lines
                        if config.utc_to_shift_local(l["end_time"]).date() < fields.Date.to_date(l["plan_date"]))
            return (late, sum(u["qty"] for u in unassigned), sum(1 for l in lines if l["changeover_needed"]), early)

        best_override = {}
        best = run_once(best_override); best_obj = objective(best[0], best[1])
        attempts, accepted, stop = 0, 0, "no_hard_violation"
        if best_obj[0] > 0 or best_obj[1] > 0:
            stop = "limit"
            tried = set()
            while attempts < max_attempts:
                # 하드 위반이 있는 제품의 금형을 다른 적합 호기로 옮겨 본다
                targets = {l["product_id"] for l in best[0] if config.utc_to_shift_local(l["end_time"]).date() > fields.Date.to_date(l["plan_date"])}
                targets |= {u["product_id"] for u in best[1] if u["reason"] == "no_capacity"}
                moved = False
                for pid in sorted(targets):
                    for cap in sorted(product_caps.get(pid, []), key=lambda c: (c.mold_id.id, c.workcenter_id.id)):
                        key = (cap.mold_id.id, cap.workcenter_id.id)
                        if key in tried or best_override.get(cap.mold_id.id) == cap.workcenter_id.id:
                            continue
                        tried.add(key); attempts += 1
                        trial = dict(best_override); trial[cap.mold_id.id] = cap.workcenter_id.id
                        cand = run_once(trial); obj = objective(cand[0], cand[1])
                        if obj < best_obj:
                            best, best_obj, best_override, accepted, moved = cand, obj, trial, accepted + 1, True
                        if attempts >= max_attempts:
                            break
                    if moved or attempts >= max_attempts:
                        break
                if not moved:
                    stop = "no_improvement" if attempts else "no_candidates"; break
                if best_obj[0] == 0 and best_obj[1] == 0:
                    stop = "resolved"; break
            if attempts and best_override:
                best = run_once(best_override)      # 최종 채택안으로 창·예약 상태를 남긴다
        lines, unassigned, changeovers, issues = best
        stats.update({"attempts": attempts, "accepted": accepted, "stop": stop, "objective_late_unassigned_changeovers_early": list(best_obj)})
        plan_issues = self.env.context.get("plan_issues")
        if plan_issues is not None:
            plan_issues.extend(issues)
            plan_issues.append("개선 탐색: 시도 %d·채택 %d·종료 %s(상한 %d). 휴리스틱이라 전역 최적을 보장하지 않는다."
                               % (attempts, accepted, stop, max_attempts))
        for u in unassigned:
            h["drop"](u["product_id"], u["plan_date"], u["qty"], u["reason"], u["detail"])
        return lines, h["unassigned_list"]

    # ─────────────────────────────────────────────
    # [R135] 일별 순서 · 최종 궤적 평가 · 수동 수정 재검증
    # ─────────────────────────────────────────────
    def _r135_due_end(self, config, wc_id, day):
        """필요일 D 의 납기 상한(현지 naive). D 에 시작하는 교대 창 중 마지막 창의 끝 — 야간이 자정을 넘어도
        그 날의 작업이다(첫 실행에서 자정 통과 야간을 '1일 지연' 으로 세던 것을 고침). 창이 없으면 23:59:59."""
        Avail = self.env["injection.machine.availability"]
        av = Avail.search([("workcenter_id", "=", wc_id), ("date", "=", str(day))], limit=1) if wc_id else Avail
        dh = av.day_shift_hours if av else (config.day_shift_hours or 0.0)
        nh = av.night_shift_hours if av else (config.night_shift_hours or 0.0)
        day_start, night_start = config.get_shift_start_hours()
        ends = []
        if dh and dh > 0:
            ends.append(datetime.combine(day, config.hour_float_to_time(day_start)) + timedelta(hours=dh))
        if nh and nh > 0:
            ends.append(datetime.combine(day, config.hour_float_to_time(night_start)) + timedelta(hours=nh))
        return max(ends) if ends else datetime.combine(day, datetime_time.max.replace(microsecond=0))

    @staticmethod
    def _expected_good(planned_qty, initial_scrap, defect_rate):
        """총생산량 → 예상 양품. (계획 − 초기불량) × (1 − 불량률). 음수는 0."""
        good = (planned_qty - (initial_scrap or 0)) * max(0.0, 1.0 - (defect_rate or 0.0) / 100.0)
        return max(0.0, good)

    def _assign_daily_sequence(self):
        """(사출기, 작업일) 안에서 시작 시각 순으로 1,2,3… 을 매기고 교체 시각·예상 양품·납기 상한을 채운다.

        [R135 기준 6] 필요일(`plan_date`)과 실제 작업일(`start_date`)을 구별한다. 자정 통과 작업은
        이미 교대 경계에서 두 라인으로 나뉘고 교체는 첫 라인에만 있으므로 여기서 중복 계산이 없다.
        확정·실행 중 라인도 **번호만** 받는다 — 시각·수량은 건드리지 않는다(기준 7).
        """
        self.ensure_one()
        config = self._get_config()
        ledger = self._planning_ledger(self._LEDGER_STATES + ("confirmed",))
        lines = ledger.line_ids.sorted(lambda l: (l.workcenter_id.id, l.start_date or l.plan_date,
                                                  l.start_time or datetime.min, l.id))
        counter, previous = {}, None
        for line in lines:
            key = (line.workcenter_id.id, line.start_date or line.plan_date)
            counter[key] = counter.get(key, 0) + 1
            co_h = line.changeover_in_span_hours or 0.0
            changeover_start = changeover_end = False
            if line.occupancy_start_time or co_h > 0:
                changeover_start = line.occupancy_start_time or line.start_time
                changeover_end = (line.start_time + timedelta(hours=co_h)) if (line.start_time and co_h > 0) else line.start_time
            due_local = self._r135_due_end(config, line.workcenter_id.id, line.plan_date)
            line.write({
                "daily_sequence": counter[key],
                "changeover_start_time": changeover_start,
                "changeover_end_time": changeover_end,
                "expected_good_qty": self._expected_good(line.planned_qty, line.initial_scrap, line.defect_rate),
                "due_end_time": config.shift_local_to_utc(due_local),
            })
        return True

    def _evaluate_plan(self, part_demands, config):
        """최종 궤적(예상 양품 기준)으로 납기·안전재고·최대재고·조기생산 위반을 기록하고 지표를 채운다.

        [R135 기준 3·4] 불량률·초기불량·최소로트·정수화가 반영된 **최종** 라인으로 다시 검사한다.
        휴리스틱 결과이므로 '실행 가능' 은 위반 0건이라는 뜻일 뿐 전역 최적이 아니다. 최대재고
        미설정은 상한 없음이지 최적 보장이 아니다. 납기 상한은 필요일 업무 종료(일자 수요 한계).
        """
        self.ensure_one()
        ledger = self._planning_ledger(self._LEDGER_STATES + ("confirmed",))
        ledger.violation_ids.unlink()
        Violation = ledger.env["injection.planning.violation"]
        safety_days = int(round(config.safety_stock_days or 0))
        safety_basis = config._safety_stock_basis()
        demand_horizon_end = max((d for _p, d in (part_demands or {}).keys()), default=None)
        lines = ledger.line_ids
        demand_by = defaultdict(lambda: defaultdict(float))
        for (pid, date_str), qty in (part_demands or {}).items():
            demand_by[pid][date_str] += qty
        good_by = defaultdict(lambda: defaultdict(float))
        for line in lines:
            good_by[line.product_id.id][str(line.finish_date or line.plan_date)] += line.expected_good_qty
        pids = set(demand_by) | set(good_by)
        products = self.env["product.product"].browse(sorted(pids))
        on_hand = self._stock_on_hand(products)
        receipts = self._scheduled_receipts(pids)
        dates = []
        day = self.plan_date_from
        while day <= self.plan_date_to:
            dates.append(str(day)); day += timedelta(days=1)
        violations, stock_end_at = [], {}
        totals = {"late": 0.0, "safety": 0.0, "excess": 0.0, "early": 0.0}
        for product in products:
            pid = product.id
            running = on_hand.get(pid, 0.0)
            demand_dates = sorted(demand_by[pid])
            max_inv = product.max_inventory_qty or 0.0
            for date_str in dates:
                running += receipts.get(pid, {}).get(fields.Date.to_date(date_str), 0.0)
                end = running + good_by[pid].get(date_str, 0.0) - demand_by[pid].get(date_str, 0.0)
                stock_end_at[(pid, date_str)] = end
                target, complete = self._safety_stock_target(demand_by[pid], date_str, safety_days, safety_basis, demand_horizon_end)
                if not complete and safety_days:
                    violations.append({"product_id": pid, "plan_date": date_str, "kind": "demand_horizon_short", "severity": "notice",
                                       "qty": target, "detail": "D+%d 까지의 수요가 수집 범위(%s)를 넘어 안전재고 목표가 불완전함 — 미수집을 0 으로 단정하지 않음" % (safety_days, demand_horizon_end)})
                if target > 0 and end + 1e-6 < target:
                    violations.append({"product_id": pid, "plan_date": date_str, "kind": "safety_shortfall", "severity": "policy",
                                       "qty": target - end, "detail": "종료 재고 %.0f < 안전재고 목표 %.0f(%s, N=%d)" % (end, target, "달력일" if safety_basis == "calendar_days" else "수요가 있는 날짜", safety_days)})
                    totals["safety"] += target - end
                if max_inv > 0 and end > max_inv + 1e-6:
                    violations.append({"product_id": pid, "plan_date": date_str, "kind": "max_inventory_excess", "severity": "policy",
                                       "qty": end - max_inv, "detail": "종료 재고 %.0f > 최대재고 %.0f" % (end, max_inv)})
                    totals["excess"] += end - max_inv
                running = end
        for line in lines:
            finish = line.finish_date or line.plan_date
            end_local = config.utc_to_shift_local(line.end_time).replace(tzinfo=None) if line.end_time else None
            due_local = self._r135_due_end(config, line.workcenter_id.id, line.plan_date)
            if end_local and end_local > due_local:
                days = max(1, (end_local.date() - line.plan_date).days)
                violations.append({"product_id": line.product_id.id, "plan_date": line.plan_date, "kind": "late", "severity": "hard",
                                   "qty": line.expected_good_qty, "days": days,
                                   "detail": "%s 완료일 %s 가 필요일보다 %d일 늦음(가동시간 부족·앞 작업 점유)" % (line.workcenter_id.name, finish, days)})
                totals["late"] += line.expected_good_qty
            elif finish < line.plan_date:
                days = (line.plan_date - finish).days
                violations.append({"product_id": line.product_id.id, "plan_date": line.plan_date, "kind": "early_production", "severity": "notice",
                                   "qty": line.expected_good_qty, "days": days,
                                   "detail": "필요일보다 %d일 먼저 생산(교체 최소화 또는 납기 준수용 선행)" % days})
                totals["early"] += line.expected_good_qty
            line.write({"projected_stock_end": stock_end_at.get((line.product_id.id, str(finish)), 0.0)})
        for v in violations:
            v["planning_run_id"] = self.id
        if violations:
            Violation.create(violations)
        hard = bool(totals["late"] > 0 or ledger.unassigned_ids)
        # [검토 #1] 불가능 '입증' 은 자원 하한으로만: 하드 위반이 전부 물리 제약(조합 없음·형체력·금형 상태)이거나
        # 자원 총량 부족(no_capacity)으로 미배정된 경우. 납기 지연이 섞이면 순서를 바꿔 해결될 수 있으므로 '미해결'.
        proven = bool(ledger.unassigned_ids) and totals["late"] == 0 and all(
            u.reason in ("no_capacity", "no_capability", "clamping", "mold_state") for u in ledger.unassigned_ids)
        feasibility = "feasible" if not hard else ("infeasible_proven" if proven else "infeasible_unresolved")
        search = self.env.context.get("r135_search_stats") or "해당 없음(기존 방식)"
        note = ("순서 계산 방식: %s(계산 당시 스냅샷). 휴리스틱(전역 최적 미보장). 우선순위: 물리·품질·확정 제약 → 납기 → "
                "재고 범위 → 교체 최소. 납기 상한 = 필요일 업무 종료(일자 수요만 있어 시각 납기·BR 2시간은 입증하지 않음). "
                "안전재고 = %s(N=%d, 사용자 확정 기본 3·설정에서 변경; 달력일은 아스트라 명시 가정). "
                "최대재고 미설정 = 상한 미설정(최적재고 충족 판정 아님; 기준정보 미비). "
                "지연 수량 = 수요별 원 납기(그 날 시작하는 마지막 교대 끝) 이후 완료된 예상 양품 합(수요별로 세며 일별 중복 누적 없음; 안전재고 선행분은 덮는 실수요 날짜가 납기). "
                "지표: 교체 %d회, 납기 지연 %.0f(하드), 미배정 %.0f(하드), 안전재고 부족 %.0f(정책), 최대재고 초과 %.0f(정책), 조기생산 %.0f(안내). 개선 탐색: %s."
                % (self.sequencing_mode_snapshot or config.sequencing_mode, "D+1~D+N 달력일 수요 합" if safety_basis == "calendar_days" else "다음 N개 수요가 있는 날짜의 수요 합", safety_days, sum(1 for l in lines if l.changeover_needed),
                   totals["late"], sum(ledger.unassigned_ids.mapped("qty")), totals["safety"], totals["excess"], totals["early"], search))
        super(PlanningRun, self.sudo()).write({
            "feasibility": feasibility, "sequencing_note": note,
            "total_changeovers": sum(1 for l in lines if l.changeover_needed),
            "late_qty": totals["late"], "safety_shortfall_qty": totals["safety"],
            "max_excess_qty": totals["excess"], "early_qty": totals["early"]})
        issues = self.env.context.get("plan_issues")
        if issues is not None and violations:
            issues.append("계획 위반 %d건(납기 %.0f·안전재고 %.0f·최대재고 %.0f·조기 %.0f) — '계획 위반·지표' 탭 참조"
                          % (len(violations), totals["late"], totals["safety"], totals["excess"], totals["early"]))
        return violations

    def action_apply_manual_order(self):
        """담당자가 `daily_sequence` 를 고친 뒤 — 그 순서대로 초안 라인의 **시간을 다시 놓는다**.

        [R135 검토 #5] '시간 수정 → 순서 재유도'(`action_revalidate_sequence`)와 구별되는 액션이다.
        초안·MO 없는 라인만 다시 배치하고(확정 MO 보존), 교체·예상 양품·원재료 소요·재고 궤적을 모두 갱신한 뒤
        검증한다. 초안 라인은 다시 만들어진다(id 가 바뀐다).
        """
        self.ensure_one()
        if self.state != "review":
            raise UserError(_("검토 상태의 계획만 수동 순서를 재배치할 수 있습니다."))
        config = self._get_config()
        draft = self.line_ids.filtered(lambda l: l.state == "draft" and not l.mo_id)
        if not draft:
            raise UserError(_("재배치할 초안 라인이 없습니다(확정·MO 라인은 건드리지 않습니다)."))
        fixed = self.line_ids - draft
        extra_busy, extra_mold_busy = defaultdict(list), defaultdict(list)
        for line in fixed.filtered(lambda l: l.start_time and l.end_time):
            start = config.utc_to_shift_local(line.occupancy_start_time or line.start_time).replace(tzinfo=None)
            end = config.utc_to_shift_local(line.end_time).replace(tzinfo=None)
            extra_busy[line.workcenter_id.id].append([start, end]); extra_mold_busy[line.mold_id.id].append([start, end])
        jobs = defaultdict(list)
        for line in draft.sorted(lambda l: (l.workcenter_id.id, l.start_date or l.plan_date, l.daily_sequence, l.start_time or datetime.min, l.id)):
            jobs[line.workcenter_id.id].append({
                "product_id": line.product_id.id, "mold_id": line.mold_id.id, "qty": line.planned_qty,
                "demand_qty": line.demand_qty, "plan_date": str(line.plan_date),
                "defect_rate": line.defect_rate, "initial_scrap": line.initial_scrap})
        issues = []
        scoped = self.with_context(plan_issues=issues, r135_manual_jobs=dict(jobs),
                                   r135_extra_busy=dict(extra_busy), r135_extra_mold_busy=dict(extra_mold_busy),
                                   r135_search_stats={"manual_order": True})
        lines_data, _unassigned = scoped._schedule({}, config)
        ledger = self._planning_ledger(("review",))
        ledger.unassigned_ids.unlink()
        draft.with_env(ledger.env).unlink()
        if lines_data:
            ledger.env["injection.planning.line"].create(lines_data)
        scoped._assign_daily_sequence()
        scoped._calculate_material_requirements()
        part_demands = scoped._explode_bom()
        scoped._generate_daily_summary(part_demands, config)
        violations = scoped._evaluate_plan(part_demands, config)
        self._clear_derived_stale()
        self.message_post(body=Markup("<b>수동 순서 재배치</b> — 초안 라인 %d→%d, 위반 %d건, 경고 %d건<br/>"
                                      % (len(draft), len(lines_data), len(violations), len(issues))
                                      + "<br/>".join("· " + i for i in issues)))
        return True

    def action_revalidate_sequence(self):
        """담당자가 순서·수량·금형·기계·시각을 손으로 고친 뒤 — 최적화를 다시 돌리지 않고 검증만 한다.

        [R135 기준 7] (a) 일별 순서 재유도 (b) 사출기·금형별 시각 겹침 (c) 납기·재고 궤적 위반 재계산.
        확정·실행 중 MO 라인은 재배치하지 않는다(번호·표시만). MO·작업지시·원재료 일시는 라인 시각을
        그대로 쓰는 기존 경로가 유지한다.
        """
        self.ensure_one()
        if self.state not in ("review", "confirmed"):
            raise UserError(_("검토 또는 확정 상태의 계획만 재검증할 수 있습니다."))
        config = self._get_config()
        issues = []
        self = self.with_context(plan_issues=issues)
        self._assign_daily_sequence()
        for group_field, label in (("workcenter_id", "사출기"), ("mold_id", "금형")):
            by_resource = defaultdict(list)
            for line in self.line_ids.filtered(lambda l: l.start_time and l.end_time):
                by_resource[line[group_field].id].append(line)
            for res_id, rows in by_resource.items():
                rows.sort(key=lambda l: (l.occupancy_start_time or l.start_time, l.id))
                for prev, cur in zip(rows, rows[1:]):
                    cur_from = cur.occupancy_start_time or cur.start_time
                    if cur_from < prev.end_time:
                        issues.append("%s 시각 겹침: %s (%s~%s) ↔ %s (%s~)" % (
                            label, prev.display_name, prev.start_time, prev.end_time, cur.display_name, cur_from))
        part_demands = self._explode_bom()
        violations = self._evaluate_plan(part_demands, config)
        self.message_post(body=Markup("<b>순서 재검증</b> — 위반 %d건, 경고 %d건<br/>" % (len(violations), len(issues))
                                      + "<br/>".join("· " + i for i in issues)))
        return True

    # ─────────────────────────────────────────────
    # MO 생성
    # ─────────────────────────────────────────────
    def _assert_company_scope(self):
        """이 계획을 실행할 자격이 있는 회사인가.

        PR08: 회사 A 만 소속·허용된 담당자가 회사 B 계획으로 MO 를 만들 수 있었다.
        record rule 이 조회·쓰기를 막지만, **실행 메서드는 자기 스스로도 확인해야
        한다** — sudo 를 거쳐 온 호출이나 규칙이 꺼진 경로가 그대로 통과하기 때문이다.
        """
        self.ensure_one()
        user = self.env.user
        if self.company_id and self.company_id not in user.company_ids:
            raise AccessError(_(
                "다른 회사(%(company)s)의 계획입니다. 실행할 수 없습니다. (%(name)s)",
                company=self.company_id.display_name, name=self.name))

    def _get_mo_candidate_lines(self):
        """현재 실행에서 아직 MO로 전환되지 않은 계획 라인을 반환한다.

        확인 위자드의 요약과 실제 생성 로직이 같은 대상 집합을 사용하도록
        단일 진입점으로 둔다. 부분 실패 후 재시도할 때도 draft 라인만 남는다.
        """
        self.ensure_one()
        # `state` 만 보면 안 된다. PR10 처럼 생성 뒤 확정에서 실패해 상태가 draft 로
        # 남은 라인에 이미 MO 가 붙어 있으면, 재시도가 같은 라인에 MO 를 또 만든다.
        return self.line_ids.filtered(
            lambda line: line.state == "draft" and not line.mo_id)

    def _assert_confirmable_plan(self):
        """[R135 검토 #4] 목록 경고만으로 정상 확정되는 경로를 남기지 않는다 — 서버에서 막는다.

        하드 위반(납기 지연·미배정)이나 오래된 파생값이면 확정·MO 생성 불가. 정책 위반(재고 범위)은
        관리자가 명시적으로 확인한 뒤에만 가능. 안내(조기생산)는 막지 않는다.
        """
        for run in self:
            if run.settings_changed:
                # [사용자 23fd5d8] 설정을 바꾼 뒤의 오래된 초안은 방식과 무관하게 최신 정책 계산처럼 확정하지 않는다.
                raise UserError(_("계산 뒤 안전재고 일수·계산 방식 설정이 바뀌었습니다(적용 %(d)d일/%(b)s). 초안으로 되돌려 재계산한 뒤 확정하십시오.",
                                  d=run.safety_stock_days_applied, b=run.safety_stock_basis_applied))
            if run.sequencing_mode_snapshot != "setup_aware":
                # [Q3·#8] 기존 방식 계획의 위반 게이트는 이전 확정 규칙 그대로(`_assert_derived_fresh` 만). 첫 실행에서
                # 이 게이트가 legacy 회귀 24건을 막았다 — 야간 자정 통과를 지연으로, 풀 캐퍼 초과를 미배정으로.
                continue
            if run.derived_stale:
                raise UserError(_("계획 라인이 손으로 바뀐 뒤 재검증되지 않았습니다. '순서 재검증' 또는 '소요 재검증' 을 먼저 실행하십시오."))
            hard = run.violation_ids.filtered(lambda v: v.severity == "hard")
            if hard or run.feasibility in ("infeasible_proven", "infeasible_unresolved"):
                raise UserError(_("하드 위반(납기 지연·미배정)이 있는 계획은 확정할 수 없습니다: %s") % (
                    "; ".join(hard.mapped("detail")[:3]) or run.feasibility))
            policy = run.violation_ids.filtered(lambda v: v.severity == "policy")
            if policy and not run.violations_acknowledged:
                raise UserError(_("재고 범위 위반 %d건이 있습니다. 관리자가 '정책 위반 확인' 을 누른 뒤에만 확정할 수 있습니다.") % len(policy))
        return True

    def action_acknowledge_violations(self):
        self.ensure_one()
        if not self.env.user.has_group("injection_planning.group_planning_manager"):
            raise AccessError(_("정책 위반 확인은 생산계획 관리자만 할 수 있습니다."))
        if self.violation_ids.filtered(lambda v: v.severity == "hard"):
            raise UserError(_("하드 위반은 확인으로 넘길 수 없습니다. 계획을 고치십시오."))
        super(PlanningRun, self.sudo()).write({"violations_acknowledged": True, "violations_acknowledged_by": self.env.user.id})
        self.message_post(body=_("정책 위반 %d건을 %s 이(가) 확인했습니다.") % (
            len(self.violation_ids.filtered(lambda v: v.severity == "policy")), self.env.user.name))
        return True

    def action_confirm_generate_mo(self):
        self._assert_confirmable_plan()
        """확정 → MO 일괄 생성"""
        self.ensure_one()
        self._assert_company_scope()
        self._assert_derived_fresh(_("MO 생성"))
        candidates = self._get_mo_candidate_lines()
        if not candidates:
            raise UserError(_("MO 생성 대상 계획 라인이 없습니다."))
        # 위자드를 열기 전에 막는다 — 확인 화면까지 갔다가 거절당하지 않게.
        # (백스톱은 `_validate_planning_line`. 위자드를 건너뛴 직접 호출도 막힌다.)
        for line in candidates:
            self._validate_planning_line(line)
        return {
            "type": "ir.actions.act_window",
            "name": "MO 생성 확인",
            "res_model": "injection.generate.mo.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_planning_run_id": self.id},
        }

    def _line_fitness_problem(self, line):
        """이 라인을 **지금** 실행해도 되는가. 저장된 표시가 아니라 마스터를 다시 읽는다.

        PR01·PR02: 잠금이 라인의 `fit_unverified` 값에 기대고 있었다. 그 값은 사람이
        고칠 수 있고(marker=False 직접 쓰기), 계산한 뒤에 금형을 정비중으로 돌리거나
        호기 형체력을 낮춰도 저장된 값은 그대로다. 확정은 계산 시점의 기억이 아니라
        **실행 직전의 사실**로 판단해야 한다.

        문제가 있으면 사람이 읽을 사유를, 없으면 False 를 돌려준다.
        """
        mold, wc = line.mold_id, line.workcenter_id
        if not mold or not wc:
            return _("호기 또는 금형이 지정되지 않았습니다.")
        if not mold.active or mold.state != "active":
            return _(
                "금형 %(mold)s 이(가) 실행 가능한 상태가 아닙니다(%(state)s).",
                mold=mold.display_name or mold.code,
                state=dict(mold._fields["state"].selection).get(mold.state)
                if mold.active else _("보관 해제"))
        cap = self.env["injection.machine.mold.capability"].search([
            ("workcenter_id", "=", wc.id), ("mold_id", "=", mold.id),
            ("active", "=", True)], limit=1)
        if not cap:
            return _("사출기 %(machine)s 와 금형 %(mold)s 의 조합이 더 이상 없습니다.",
                     machine=wc.name, mold=mold.display_name or mold.code)
        need = mold.required_clamping_ton or 0.0
        have = wc.x_clamping_force_ton or 0.0
        if need and not have:
            return _(
                "사출기 %(machine)s 의 형체력이 등록되지 않아 금형 %(mold)s 의 "
                "요구 %(need).0f톤을 만족하는지 확인할 수 없습니다.",
                machine=wc.name, mold=mold.display_name or mold.code, need=need)
        if need and have + 1e-6 < need:
            return _(
                "사출기 %(machine)s 의 형체력 %(have).0f톤이 금형 %(mold)s 의 "
                "요구 %(need).0f톤에 미치지 못합니다.",
                machine=wc.name, have=have,
                mold=mold.display_name or mold.code, need=need)
        company = self.company_id
        if company:
            for record, label in ((mold, _("금형")), (wc, _("사출기")),
                                  (line.product_id, _("품목"))):
                other = getattr(record, "company_id", False)
                if other and other != company:
                    return _(
                        "%(label)s %(name)s 은(는) 다른 회사(%(other)s)의 자료입니다.",
                        label=label, name=record.display_name,
                        other=other.display_name)
        return False

    def _validate_planning_line(self, line):
        """MO 생성 전 라인 검증 훅 — 확장 모듈(worksite 등)이 오버라이드.
        검증 실패는 UserError 로 전체 생성을 중단시킨다(계획자가 먼저 고칠 문제)."""
        occupied_from = line.occupancy_start_time or line.start_time
        if self.schedule_not_before and (not occupied_from or occupied_from < self.schedule_not_before):
            raise UserError(_("교체·생산 배정이 지정한 시작 하한보다 빠릅니다. 계획을 다시 계산하십시오."))
        problem = self._line_fitness_problem(line)
        if problem:
            # 적합성이 확인되지 않은 배정은 초안·검토 단계에서 **보여 주되** 실행으로
            # 넘기지 않는다. 경고만 달린 실행 가능 배정으로 확정하면, 마스터가 빈
            # 채로 현장에 지시가 나간다. (아스트라 2026-09-10 18:41 / PR01·PR02)
            raise UserError(_(
                "실행 직전 검증에서 걸린 계획 라인이 있어 MO 를 생성할 수 없습니다.\n"
                "· %(product)s %(qty).0f개 (%(machine)s / %(mold)s)\n"
                "· %(problem)s\n"
                "기준정보를 바로잡은 뒤 '초안으로' 되돌려 다시 계산하십시오.",
                product=line.product_id.display_name, qty=line.planned_qty,
                machine=line.workcenter_id.name or "-",
                mold=line.mold_id.display_name or "-", problem=problem))
        return True

    def _validate_created_mo(self, line, mo):
        """MO 를 만든 **뒤** 계획과 실제가 맞는지 대사한다. 확장 모듈이 덧붙이는 훅.

        계획이 정한 시각을 vals 로 넘겨도 Odoo 코어가 설비 작업달력으로 종료 시각을
        다시 계산한다(점심 휴게가 낀 달력이면 08~16 작업이 17 시 종료가 된다). 그러면
        계획의 가동창과 MO 의 예정 종료가 어긋나고, 날짜별 가용재고 계산이 그 위에서
        돈다. 코어의 종료만 덮으면 8시간 작업을 7시간 가용창에 밀어 넣는 셈이라
        그렇게 고치지 않는다 — **어긋났다는 사실을 잡아 보류**한다.
        (아스트라 2026-09-10 19:51)

        불일치는 `UserError` 로 올린다. 호출부가 같은 savepoint 안에서 되돌린다.
        """
        self.ensure_one()
        company = self.company_id or self.env.company
        if mo.company_id != company:
            raise UserError(_(
                "생성된 MO 의 회사(%(mo)s)가 계획의 회사(%(plan)s)와 다릅니다.",
                mo=mo.company_id.display_name, plan=company.display_name))
        planned_end = line.end_time
        actual_end = mo.date_finished
        # [445 계획 리뷰 (2)] 5분 허용은 숫자 잔차 회피를 넘어 **실제 5분 납기 지연을
        # 승인**하는 값이었다. 업무상 여유를 여기서 임의로 정하지 않는다. 잔차는
        # 배치 계산을 초 단위로 끊어 원천에서 없앴으므로(`_take_job`) 저장 정밀도
        # (Odoo datetime = 초)만큼인 1초만 허용한다.
        tolerance_seconds = 1
        if (line.start_time and mo.date_start
                and abs((mo.date_start - line.start_time).total_seconds()) > tolerance_seconds):
            raise UserError(_('제조오더 시작 시각이 확정 계획 시작 시각과 다릅니다. 시작·종료를 함께 검증하십시오.'))
        if (line.start_time and not mo.date_start) or (planned_end and not actual_end):
            raise UserError(_('제조오더에 계획과 대사할 시작·종료 시각이 없습니다.'))
        if planned_end and actual_end:
            planned_end = planned_end.replace(microsecond=0)
            actual_end = actual_end.replace(microsecond=0)
        # [아스트라] 양방향 대사 — **줄어드는 쪽**도 막는다. 소요 원천이 연결되지
        # 않으면 코어 60분 fallback 으로 축소되는데, 그것을 통과시키지 않는다.
        if (planned_end and actual_end and mo.date_start
                and (planned_end - actual_end).total_seconds() > tolerance_seconds):
            config = self._get_config()
            raise UserError(_(
                "제조오더의 소요시간이 계획보다 짧습니다. 계획 생산시간의 원천이 "
                "제조오더에 연결되지 않았습니다.\n"
                "· %(product)s %(qty).0f개 (%(machine)s)\n"
                "· 계획 종료 %(planned)s / 제조오더 종료 %(actual)s\n"
                "이 사출기·금형의 능력(사이클·캐비티)과 작업 달력을 확인한 뒤 다시 "
                "생성하십시오. 종료 시각만 덮어쓰지 않습니다.",
                product=line.product_id.display_name, qty=line.planned_qty,
                machine=line.workcenter_id.name or "-",
                planned=config.utc_to_shift_local(planned_end).strftime("%Y-%m-%d %H:%M"),
                actual=config.utc_to_shift_local(actual_end).strftime("%Y-%m-%d %H:%M")))
        if (planned_end and actual_end
                and (actual_end - planned_end).total_seconds() > tolerance_seconds):
            # 설비 작업달력(휴게·휴무·이미 예약된 작업)이 계획의 가동창보다 좁다.
            config = self._get_config()
            raise UserError(_(
                "계획한 종료 시각과 설비 작업달력이 맞지 않습니다.\n"
                "· %(product)s %(qty).0f개 (%(machine)s)\n"
                "· 계획 종료 %(planned)s / 설비 달력 기준 종료 %(actual)s\n"
                "사출기의 작업 달력(휴게·휴무·기존 예약)과 생산계획 설정의 교대 시간이 "
                "같은 시간을 가리키도록 맞춘 뒤 다시 계산하십시오.",
                product=line.product_id.display_name, qty=line.planned_qty,
                machine=line.workcenter_id.name or "-",
                planned=config.utc_to_shift_local(planned_end).strftime("%Y-%m-%d %H:%M"),
                actual=config.utc_to_shift_local(actual_end).strftime("%Y-%m-%d %H:%M")))
        return True

    def _get_mo_vals(self, line, bom):
        """MO vals 단일 훅 — 확장 모듈은 generate 전체가 아니라 이 훅만 오버라이드한다.
        (한쪽 수정이 다른 쪽에 누락되는 이중 유지보수 방지)"""
        MO = self.env["mrp.production"]
        mo_vals = {
            "product_id": line.product_id.id,
            "product_qty": line.planned_qty,
            "bom_id": bom.id if bom else False,
            "date_start": line.start_time or fields.Datetime.now(),
            # MO 가 **계획 소요의 원천**으로 되돌아갈 수 있게 라인을 남긴다
            # (`_injection_plan_expected_finish` 가 이 라인의 능력·수량·교체를 쓴다).
            "planning_line_id": line.id,
            # 계획의 회사를 그대로 넘긴다. 비워 두면 **활성 회사**로 만들어져
            # 회사 B 계획에 회사 A 의 MO 가 달린다. (PR08)
            "company_id": (self.company_id or self.env.company).id,
            "planning_run_id": self.id,
        }
        # [아스트라 10:14 #4] 소요의 원천을 **확정 시점에 얼려** 넘긴다. 나중에 능력
        # 마스터가 바뀌거나 보관처리돼도 이 MO 의 소요는 흔들리지 않는다.
        # 계획이 구간을 쪼갤 때 쓴 것과 **같은 raw 능력**(`hourly_capacity`)이다.
        capability = self.env["injection.machine.mold.capability"].search([
            ("workcenter_id", "=", line.workcenter_id.id),
            ("mold_id", "=", line.mold_id.id),
            ("active", "=", True),
        ], limit=1) if (line.workcenter_id and line.mold_id) else None
        if capability and capability.hourly_capacity > 0:
            mo_vals["planning_hourly_capacity"] = capability.hourly_capacity
            mo_vals["planning_changeover_hours"] = line.changeover_in_span_hours or 0.0
        if line.end_time and "date_finished" in MO._fields:
            # 계획이 정한 완료 예정 시각을 정본으로 넘긴다. 넘기지 않으면 표준
            # 리드타임이 다른 시각을 만들어 날짜별 가용재고 계산과 어긋난다.
            # (아스트라 PP05 추가 관찰)
            mo_vals["date_finished"] = line.end_time
        # 사출 현장(injection_worksite) 연계 — 계획 배정 결과(호기·금형)를 MO 에 전달.
        # 미전달 시 PLC 단위실적이 계획 MO 를 찾지 못해 현장 연동이 끊긴다.
        # worksite 미설치 환경(계획 단독)에서도 동작하도록 필드 존재 검사로 가드.
        if line.workcenter_id and "workcenter_id" in MO._fields:
            mo_vals["workcenter_id"] = line.workcenter_id.id
        if "is_injection_mo" in MO._fields:
            mo_vals["is_injection_mo"] = True
        if line.mold_id and "actual_mold_id" in MO._fields:
            mo_vals["actual_mold_id"] = line.mold_id.id
        if "inj_shift" in MO._fields:
            # 계획 단계엔 교대 정보가 없음 — 주간 기본, 현장 개시 시 변경
            mo_vals["inj_shift"] = "day"
        return mo_vals

    def _lock_for_mo_generation(self):
        """같은 계획에 대한 MO 생성을 한 줄로 세운다.

        savepoint 는 **한 요청 안의** 원자성만 보장한다. 두 요청이 동시에 들어오면
        둘 다 같은 draft 라인을 후보로 읽고 각자 MO 를 만든다 — 라인당 MO 1개라는
        규칙이 깨진다. 격리 실행에서 확인한 Odoo 트랜잭션은 Repeatable Read다.
        계획 행을 잠그고 첫 요청의 commit과 충돌하면 SerializationFailure를 전파해
        전체 요청을 새 트랜잭션으로 재시도해야 한다. 캐시 무효화만으로 DB snapshot이
        갱신되지는 않는다. 새 요청에서 기존 mo_id/발주 잔량을 다시 검사한다.

        `FOR UPDATE`는 트랜잭션이 끝날 때까지 유지된다. 첫 요청이 rollback한 경우에는
        대기 요청이 진행하며, commit 경합은 전체 재시도 계약을 통해 중복을 차단한다.
        (아스트라 배정 — 같은 계획 MO 동시 생성 직렬화)
        """
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute(
            "SELECT id FROM injection_planning_run WHERE id = %s FOR UPDATE", (self.id,))
        # ORM 캐시를 무효화한다. DB snapshot 갱신은 새 트랜잭션 재시도가 담당한다.
        self.invalidate_recordset()

    def _lock_shared_resources(self, lines):
        """확정에 걸린 **공유 자원**(사출기·금형)을 정해진 순서로 잠그고 행 버전을 올린다.

        계획 행 잠금은 **같은 계획**의 동시 요청만 막는다. 서로 다른 계획 둘이 같은
        설비의 같은 시간을 미리 계산해 두고 각자 확정하면 서로를 막지 못한다
        (N-CROSSPLAN-CONFIRM 에서 실제로 MO 두 개가 같은 창에 커밋됐다).

        그래서 **설비·금형 행 자체**를 잡는다. 잡는 순서를 id 오름차순으로 고정해
        교착을 피한다. 그리고 **행을 바꾼다** — Repeatable Read 에서는 잠금만으로는
        낡은 스냅샷이 그대로 보이기 때문이다. 다른 트랜잭션이 이 행을 바꿔 커밋했다면
        여기의 `FOR UPDATE` 가 직렬화 오류를 내고, 요청 전체가 새 스냅샷으로 다시 실행된다.
        """
        self.ensure_one()
        self.env.flush_all()
        for table, ids in (("mrp_workcenter", sorted(set(lines.mapped("workcenter_id").ids))),
                           ("injection_mold", sorted(set(lines.mapped("mold_id").ids)))):
            if not ids:
                continue
            self.env.cr.execute(
                "SELECT id FROM %s WHERE id IN %%s ORDER BY id FOR UPDATE" % table,
                (tuple(ids),))
            self.env.cr.execute(
                "UPDATE %s SET x_planning_reservation_seq = "
                "COALESCE(x_planning_reservation_seq, 0) + 1 WHERE id IN %%s" % table,
                (tuple(ids),))
        # 잠근 뒤의 사실로 다시 읽는다.
        self.env.invalidate_all()

    def _assert_reservation_is_still_free(self, lines):
        """확정 직전에 **다른 계획의 예약과 겹치지 않는지** 다시 대사한다.

        계산 시점의 예약 제외는 그때의 사실이다. 두 계획을 미리 계산해 두고 하나를
        확정하면, 다른 계획의 라인은 이미 남의 시간이 된다. 실행하는 순간 다시 본다.
        """
        self.ensure_one()
        Line = self.env["injection.planning.line"]
        WorkOrder = self.env.get("mrp.workorder")
        checked = []

        def occupied_from(row):
            """설비를 **실제로 잡기 시작한** 시각 — 교체만 한 앞 구간을 포함한다.

            [아스트라 20260912 10:06] 「`occupancy_start_time` 을 예약 조회 계산에는
            추가했지만 **`_assert_reservation_is_still_free` 확정 충돌 검사는 기존
            `start_time` 만 사용합니다.** 서로 다른 계획 A/B 를 둘 다 미리 계산 →
            A 확정 → B 확정 경로에서는 **계산 단계 보호를 지나쳐** 교체창 겹침이
            남을 수 있습니다.」

            맞습니다. 계산 시점만 고치고 **확정 시점을 빼먹었습니다.**
            """
            return row.occupancy_start_time or row.start_time

        for line in lines:
            if not (line.start_time and line.end_time and line.workcenter_id):
                continue
            mine_from = occupied_from(line)
            for other in checked:
                if (mine_from < other.end_time
                        and occupied_from(other) < line.end_time
                        and (line.workcenter_id == other.workcenter_id
                             or (line.mold_id and line.mold_id == other.mold_id))):
                    raise UserError(_(
                        "이 계획의 라인들이 같은 시간에 동일 사출기 또는 금형을 사용합니다.\n"
                        "· %(machine)s / %(mold)s\n"
                        "겹치는 시간이나 배정을 수정하고 소요량을 다시 검증하십시오.",
                        machine=line.workcenter_id.name, mold=line.mold_id.display_name))
            checked.append(line)
            resources = [("workcenter_id", "=", line.workcenter_id.id)]
            if line.mold_id:
                resources = ["|"] + resources + [("mold_id", "=", line.mold_id.id)]
            # 겹침 판정도 **점유 시작** 기준이다. 상대 라인의 교체 구간이
            # 내 생산 앞에 있으면 `start_time` 만으로는 안 걸린다.
            clash = Line.search(resources + [
                ("id", "!=", line.id),
                ("state", "in", ("confirmed", "done")),
                ("mo_id", "!=", False),
                ("mo_id.state", "not in", ("done", "cancel")),
                ("start_time", "<", line.end_time),
                ("end_time", ">", mine_from),
            ], limit=1)
            if not clash:
                clash = Line.search(resources + [
                    ("id", "!=", line.id),
                    ("state", "in", ("confirmed", "done")),
                    ("mo_id", "!=", False),
                    ("mo_id.state", "not in", ("done", "cancel")),
                    ("occupancy_start_time", "!=", False),
                    ("occupancy_start_time", "<", line.end_time),
                    ("end_time", ">", mine_from),
                ], limit=1)
            if clash:
                raise UserError(_(
                    "같은 시간에 이 사출기 또는 금형을 사용하는 확정 계획이 있습니다.\n"
                    "· %(machine)s / %(mold)s / %(product)s\n"
                    "· 이 계획 %(mine_from)s ~ %(mine_to)s\n"
                    "· 겹치는 계획 %(other)s (%(other_from)s ~ %(other_to)s)\n"
                    "'초안으로' 되돌려 다시 계산하면 남은 시간으로 배정됩니다.",
                    machine=line.workcenter_id.name,
                    mold=line.mold_id.display_name,
                    product=line.product_id.display_name,
                    mine_from=mine_from, mine_to=line.end_time,
                    other=clash.planning_run_id.name,
                    other_from=clash.start_time, other_to=clash.end_time))
            if WorkOrder is None:
                continue
            wo_resources = [("workcenter_id", "=", line.workcenter_id.id)]
            if line.mold_id and "actual_mold_id" in self.env["mrp.production"]._fields:
                wo_resources = ["|"] + wo_resources + [
                    ("production_id.actual_mold_id", "=", line.mold_id.id)]
            busy = WorkOrder.search(wo_resources + [
                ("state", "not in", ("done", "cancel")),
                ("date_start", "<", line.end_time),
                ("date_finished", ">", mine_from),
                ("production_id", "not in", lines.mo_id.ids),
            ], limit=1)
            if busy:
                raise UserError(_(
                    "이미 잡혀 있는 작업지시와 시간이 겹칩니다.\n"
                    "· %(machine)s / %(product)s (%(mine_from)s ~ %(mine_to)s)\n"
                    "· 겹치는 작업지시 %(other)s\n"
                    "'초안으로' 되돌려 다시 계산하십시오.",
                    machine=line.workcenter_id.name,
                    product=line.product_id.display_name,
                    mine_from=line.start_time, mine_to=line.end_time,
                    other=busy.display_name))
        return True

    def generate_manufacturing_orders(self):
        self._assert_confirmable_plan()
        """실제 MO 생성 — 라인 하나가 하나의 원자 단위다.

        예전에는 create → confirm → 라인 연결을 savepoint 없이 하고 예외를 삼켰다.
        확정에서 실패하면 **draft 고아 MO 가 남고** 계획은 `confirmed` 로 끝났으며,
        같은 요청을 다시 실행하면 같은 라인에 MO 가 하나 더 생겼다. (PR09·PR10)

        지금은 이렇게 한다.
          - 라인마다 savepoint. 실패하면 그 라인이 만든 MO 까지 되돌린다(고아 0).
          - 이미 MO 가 붙은 라인은 후보에서 빠진다(업무키당 MO 1개).
          - **하나도 성공하지 못하면 상태를 옮기지 않는다.** 성공 0 인데 '확정' 으로
            끝나면 실패가 완료로 보고된다.
        """
        self.ensure_one()
        self._assert_company_scope()
        self._assert_derived_fresh(_("MO 생성"))
        self._lock_for_mo_generation()
        MO = self.env["mrp.production"].with_company(self.company_id or self.env.company)
        created_mos = self.env["mrp.production"]
        failed = []
        candidate_lines = self._get_mo_candidate_lines()
        if not candidate_lines:
            raise UserError(_("MO 생성 대상 계획 라인이 없습니다."))

        # 공유 자원을 먼저 잡고(직렬화), 그 뒤의 사실로 예약을 다시 대사한다.
        # 겹치면 **아무것도 만들지 않고** 멈춘다 — 절반만 만들어 두면 더 나쁘다.
        self._lock_shared_resources(candidate_lines)
        self._assert_reservation_is_still_free(candidate_lines)

        for line in candidate_lines:
            self._validate_planning_line(line)
            bom = self.env["mrp.bom"].find_for_purpose(
                line.product_id, "injection")
            mo_vals = self._get_mo_vals(line, bom)

            try:
                # 생성·확정·라인 연결이 함께 성립하거나 함께 없던 일이 된다.
                # [운영 bfcdb58] 사출 모듈이 단독 설치된 환경에서는 is_injection_mo 필드가 없을 수
                # 있으므로 BOM 목적을 context 로도 고정한다.
                with self.env.cr.savepoint():
                    mo = MO.with_context(bom_purpose="injection").create(mo_vals)
                    mo.action_confirm()
                    # 생성·확정 뒤 실제 값과 대사한다. 어긋나면 이 라인은 없던 일이 된다.
                    mo.flush_recordset()
                    self._validate_created_mo(line, mo)
                    line.write({"mo_id": mo.id, "state": "confirmed"})
                created_mos |= mo
                _logger.info(
                    "MO %s 생성: %s x %s",
                    mo.name, line.product_id.display_name, line.planned_qty,
                )
            except psycopg2.OperationalError:
                # 직렬화 실패·교착은 '이 라인만 실패' 가 아니다. 트랜잭션 전체가
                # 다시 실행되어야 하므로 그대로 올린다. 삼키면 중복 확정이 성공으로
                # 보고된다. (N-CROSSPLAN-CONFIRM)
                raise
            except Exception as exc:
                # savepoint 가 되돌아갔으므로 이 라인이 만든 MO 는 남지 않는다.
                _logger.exception(
                    "MO 생성 실패: product=%s, qty=%s",
                    line.product_id.display_name, line.planned_qty,
                )
                failed.append("%s×%s: %s" % (
                    line.product_id.display_name, line.planned_qty, str(exc)[:80]))

        if not created_mos:
            # 성공 0 — 상태를 옮기지 않는다. 실패 사실을 남기고 그대로 알린다.
            self.message_post(body=Markup(
                "<b>⚠ MO 생성 실패 %d건</b> — 생성된 MO 가 없어 계획을 확정하지 "
                "않았습니다.<br/>%s" % (len(failed), "<br/>".join(failed))))
            raise UserError(_(
                "제조 오더를 하나도 생성하지 못했습니다. 계획은 검토 상태 그대로입니다.\n%s",
                "\n".join(failed)))

        self.state = "confirmed"
        body = f"{len(created_mos)}건 제조 오더가 생성되었습니다."
        if failed:
            # 조용한 실패 금지 — 생성 실패분을 채터에 각인해 계획 유실을 가시화
            body += "<br/>⚠️ 생성 실패 %d건(고아 MO 없음, 재시도 가능):<br/>%s" % (
                len(failed), "<br/>".join(failed))
        self.message_post(body=Markup(body) if failed else body)
        return created_mos

    def action_cancel(self):
        """계획 취소"""
        self.ensure_one()
        self.state = "cancelled"

    def action_reset_draft(self):
        """초안으로 되돌리기.

        [P1-PP08] 생성된 MO 가 살아 있는 채로 초안으로 되돌리면, 그 MO 는 예정 입고이자
        재계획 대상이 되어 같은 수요가 두 번 계획된다. 사람이 먼저 정리해야 한다.
        """
        self.ensure_one()
        live = self.mo_ids.filtered(lambda m: m.state not in ("cancel", "done"))
        if live:
            raise UserError(_(
                "아직 살아 있는 제조 오더가 %(count)d건 있습니다: %(names)s\n"
                "초안으로 되돌리면 같은 수요가 두 번 계획됩니다. 해당 MO 를 먼저 "
                "취소하거나 완료한 뒤 다시 시도하십시오.",
                count=len(live), names=", ".join(live.mapped("name")[:5])))
        # 계획 라인 삭제도 담당자에게 직접 준 권한이 아니다(PP03). 같은 검사를 거친다.
        ledger = self._planning_ledger(self._LEDGER_STATES + ("confirmed",))
        ledger.line_ids.unlink()
        ledger.unassigned_ids.unlink()
        ledger.violation_ids.unlink()
        self.demand_ids.write({"state": "draft"})
        self.state = "draft"

    def action_view_mos(self):
        """생성된 MO 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "생성된 제조 오더",
            "res_model": "mrp.production",
            "view_mode": "list,form",
            "domain": [("planning_run_id", "=", self.id)],
        }

    # ─────────────────────────────────────────────
    # 일별 요약 (차트용)
    # ─────────────────────────────────────────────
    def _generate_daily_summary(self, part_demands, config):
        """제품별 일별 요약 데이터 생성 (재고, 수요, 생산, 안전재고)"""
        ledger = self._planning_ledger()
        Summary = ledger.env["injection.planning.daily.summary"]
        # 기존 요약 삭제
        ledger.summary_ids.unlink()

        safety_days = config.safety_stock_days or 0.0

        # 1) BOM 전개된 사출부품 수요: part_demands = {(pid, date_str): qty}
        # 제품별 일별 소요량
        demand_by_product_date = defaultdict(lambda: defaultdict(float))
        for (pid, date_str), qty in part_demands.items():
            demand_by_product_date[pid][date_str] += qty

        # 2) 계획 라인에서 제품별 일별 생산량 — **실제 완료일** 기준 (P1-PP05)
        # 필요일로 집계하면 가동시간이 모자라 다음 날로 밀린 물량이 필요일에 들어온 것처럼
        # 보인다. 차트가 JIT 결품을 숨기게 된다.
        planned_by_product_date = defaultdict(lambda: defaultdict(float))
        good_by_product_date = defaultdict(lambda: defaultdict(float))
        for line in self.line_ids:
            key = str(line.finish_date or line.plan_date)
            planned_by_product_date[line.product_id.id][key] += line.planned_qty
            good_by_product_date[line.product_id.id][key] += self._expected_good(
                line.planned_qty, line.initial_scrap, line.defect_rate)
        # [R135 기준 3] 재고에 들어오는 것은 **예상 양품**이다. 기존 방식(legacy)은 이전 동작을
        # 그대로 두고, 교체 인식 방식에서만 궤적이 양품을 쓴다. 두 값 모두 요약에 남는다.
        stock_adds = good_by_product_date if config.sequencing_mode == "setup_aware" else planned_by_product_date

        # 3) 모든 제품 수집
        all_pids = set(demand_by_product_date.keys()) | set(
            planned_by_product_date.keys()
        )
        if not all_pids:
            return

        products = self.env["product.product"].browse(list(all_pids))
        # 계산과 같은 시계열을 쓴다 — 예전에는 계산이 진행 MO 를 초기 재고에 전량
        # 더하고 차트는 qty_available 만 써서 둘이 어긋났다. (P1-PP04)
        stock_map = self._stock_on_hand(products)
        receipts = self._scheduled_receipts(all_pids)

        # 4) 계획 기간 전체 날짜 (주말 포함, 재고 연속 추적)
        from datetime import date as date_cls
        plan_from = self.plan_date_from
        plan_to = self.plan_date_to
        sorted_dates = []
        d = plan_from
        while d <= plan_to:
            sorted_dates.append(str(d))
            d += timedelta(days=1)

        if not sorted_dates:
            return

        # 5) 안전재고 계산: 각 날짜에서 향후 N일 실제 수요 합
        safety_days = int(config.safety_stock_days or 0)

        # 순수요와 같은 제품별 수요일을 사용한다. 생산일이나 다른 품목의 수요가
        # 끼어들어 안전재고 기준일을 앞당기거나, 기간 마지막 날에 처음으로 돌아가면 안 된다.
        safety_basis = config._safety_stock_basis()
        demand_horizon_end = max((d for _p, d in part_demands.keys()), default=None) if part_demands else None

        def _calc_future_demand(pid, date_str):
            return self._safety_stock_target(demand_by_product_date.get(pid, {}), date_str,
                                             safety_days, safety_basis, demand_horizon_end)[0]

        # 6) 일별 누적 재고 계산 + 레코드 생성
        vals_list = []
        for pid in all_pids:
            running_stock = stock_map.get(pid, 0)
            product_receipts = receipts.get(pid, {})
            for date_idx, date_str in enumerate(sorted_dates):
                demand = demand_by_product_date.get(pid, {}).get(date_str, 0)
                planned = planned_by_product_date.get(pid, {}).get(date_str, 0)
                good = good_by_product_date.get(pid, {}).get(date_str, 0)
                added = stock_adds.get(pid, {}).get(date_str, 0)
                # 그날 완료 예정인 기존 MO 도 그날 들어온다
                running_stock += product_receipts.get(
                    fields.Date.to_date(date_str), 0.0)
                stock_start = running_stock
                stock_end = stock_start + added - demand
                running_stock = stock_end

                # 향후 N근무일 수요 = 이 날짜에서 확보해야 할 안전재고
                safety_qty = _calc_future_demand(pid, date_str)

                vals_list.append({
                    "planning_run_id": self.id,
                    "product_id": pid,
                    "plan_date": date_str,
                    "demand_qty": demand,
                    "planned_qty": planned,
                    "expected_good_qty": good,
                    "safety_stock_qty": safety_qty,
                    "stock_start": stock_start,
                    "stock_end": stock_end,
                })

        if vals_list:
            Summary.create(vals_list)

    def _calculate_material_requirements(self):
        """계획 라인의 사출 부품 BOM을 전개하여 원재료별 총 소요량 집계.

        사출 부품(완성 사출품)의 BOM 구성품 = 원재료(레진 등).
        각 계획 라인의 planned_qty(불량·초기불량 반영된 생산량)에
        BOM 단위 소요량을 곱해 원재료별로 합산하고, 현재 가용 재고와 비교한다.
        """
        ledger = self._planning_ledger()
        Req = ledger.env["injection.planning.material.requirement"]
        Daily = ledger.env["injection.planning.material.daily"]
        # [P1-PP07] 다시 만든다고 **기존 발주 연결을 지우면 안 된다.** 원재료별로
        # 들고 있다가 새 행에 그대로 옮긴다. 이게 없으면 재검증 한 번에 '아직 발주
        # 안 한 부족분' 으로 되돌아가 같은 원재료를 또 발주하게 된다.
        previous_orders = {
            req.material_id.id: (req.purchase_order_id.id, req.ordered_qty)
            for req in ledger.material_requirement_ids
            if req.purchase_order_id
        }
        ledger.material_requirement_ids.unlink()
        ledger.material_daily_ids.unlink()

        # 원재료별 (날짜→소요량) 집계
        # 자재는 필요일이 아니라 **작업이 실제로 시작되는 날** 소비된다 (P1-PP05).
        material_date_need = defaultdict(lambda: defaultdict(float))
        for line in self.line_ids:
            consume_date = line.start_date or line.plan_date
            if not consume_date:
                continue
            bom = self.env["mrp.bom"].find_for_purpose(
                line.product_id, "injection")
            if not bom or not bom.bom_line_ids:
                continue
            bom_qty_base = bom.product_uom_id._compute_quantity(
                bom.product_qty, bom.product_tmpl_id.uom_id, round=False) or 1.0
            for bline in bom.bom_line_ids:
                # 라인 수량을 자재 기준 UoM 으로 변환 — g 등록·kg 자재 혼용 시
                # 숫자 나눗셈만 하면 소요가 뻥튀기/0.00 이 되는 결함(시연 이슈) 수정.
                # round=False: UoM 정밀도 반올림(kg=0.01)이 원단위를 뭉개지 않게
                line_qty = bline.product_uom_id._compute_quantity(
                    bline.product_qty, bline.product_id.uom_id, round=False)
                qty_per = line_qty / bom_qty_base
                material_date_need[bline.product_id.id][consume_date] += (
                    line.planned_qty * qty_per
                )

        if not material_date_need:
            return

        materials = self.env["product.product"].browse(list(material_date_need.keys()))
        avail_map = self._stock_on_hand(materials)

        req_vals = []
        daily_vals = []
        for mat_id, date_need in material_date_need.items():
            total_need = sum(date_need.values())
            available = avail_map.get(mat_id, 0.0)
            sorted_dates = sorted(date_need.keys())

            req_vals.append({
                "planning_run_id": self.id,
                "material_id": mat_id,
                "required_qty": total_need,
                "available_qty": available,
                "first_need_date": sorted_dates[0],
            })

            # 일별 누적(롤링) 재고 추이
            running = available
            for d in sorted_dates:
                need = date_need[d]
                stock_start = running
                stock_end = stock_start - need
                running = stock_end
                daily_vals.append({
                    "planning_run_id": self.id,
                    "material_id": mat_id,
                    "plan_date": d,
                    "required_qty": need,
                    "stock_start": stock_start,
                    "stock_end": stock_end,
                })

        iqc_status, iqc_note, pending = self._iqc_pending_display(materials)
        for vals in req_vals:
            carried = previous_orders.get(vals["material_id"])
            if carried:
                vals["purchase_order_id"], vals["ordered_qty"] = carried
            vals["iqc_status"] = iqc_status
            vals["iqc_status_note"] = iqc_note
            waiting = pending.get(vals["material_id"])
            if waiting:
                vals["iqc_pending_qty"], vals["iqc_reserved_qty"] = waiting
        Req.create(req_vals)
        Daily.create(daily_vals)

    def action_revalidate_requirements(self):
        """계획을 손으로 고친 뒤 파생 결과(일별 요약·원재료 소요)를 다시 만든다.

        [P1-PP07] 계획 라인을 고쳐도 원재료 소요·차트·발주량은 계산 당시 값 그대로였다.
        MO 는 바뀐 수량으로 생기고 원재료 발주는 옛 수량 기준이라 조용히 어긋난다.
        여기서는 **기존 발주 연결을 보존한 채** 파생 결과만 다시 만든다.
        """
        self.ensure_one()
        if self.state != "review":
            raise UserError(_(
                "검토 상태에서만 소요를 재검증할 수 있습니다. 확정된 계획은 "
                "'초안으로' 되돌린 뒤 다시 계산하십시오. (%s)", self.name))
        issues = []
        run = self.with_context(plan_issues=issues)
        run._generate_daily_summary(run._explode_bom(), run._get_config())
        run._calculate_material_requirements()
        self._clear_derived_stale()
        body = _("계획 변경분을 반영해 일별 요약과 원재료 소요를 다시 계산했습니다.")
        if issues:
            body += "<br/>" + "<br/>".join("· " + i for i in issues)
        self.message_post(body=Markup(body))
        return True

    def _assert_derived_fresh(self, action):
        """옛 파생 결과 위에서 실행 결정을 내리지 않는다. (P1-PP07)"""
        self.ensure_one()
        if self.derived_stale:
            raise UserError(_(
                "계획 라인을 고친 뒤 소요가 다시 계산되지 않았습니다. "
                "'소요 재검증' 을 먼저 실행하십시오.\n(막힌 작업: %(action)s / %(name)s)",
                action=action, name=self.name))

    def action_view_material_requirements(self):
        """원재료 소요/재고 목록 열기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"원재료 소요/재고 - {self.name}",
            "res_model": "injection.planning.material.requirement",
            "view_mode": "list,form",
            "domain": [("planning_run_id", "=", self.id)],
            "context": {"search_default_shortage_only": 1},
        }

    def action_view_material_daily(self):
        """원재료 일별 소요/재고 추이 열기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"원재료 일별 추이 - {self.name}",
            "res_model": "injection.planning.material.daily",
            "view_mode": "graph,list,pivot",
            "domain": [("planning_run_id", "=", self.id)],
        }

    def _iqc_pending_display(self, materials):
        """검사대기 수량 — **표시 전용**. (상태, 비고, {제품: (수량, 예약수량)})

        검사대기 재고는 Stock 하위가 아니라 형제 위치에 있어 `_stock_on_hand` 에
        **애초에 들어가지 않는다.** 여기서 다시 빼면 이중 차감이다. 그래서 부족 판정과
        발주 계산에는 쓰지 않고 화면에만 보여 준다.

        **0 과 '모른다' 를 구분한다.** 검사 모듈이 없거나 권한이 없어 못 읽었으면
        `unavailable` 로 표시한다 — 빈칸으로 두면 '검사대기 없음' 과 구별되지 않는다.
        (아스트라 2026-09-11 배정)

        수량은 검사 쪽이 알려 준 단위를 자재의 재고 단위로 환산해 담는다.
        조회는 **계획의 회사** 기준이다.
        """
        self.ensure_one()
        empty = {}
        Quant = self.env.get("stock.quant")
        if Quant is None or not hasattr(Quant, "_iqc_pending_quantities"):
            return "unavailable", _("검사(IQC) 모듈이 설치되어 있지 않습니다."), empty
        company = self.company_id or self.env.company
        try:
            rows = Quant._iqc_pending_quantities(
                company.id, product_ids=materials.ids)
        except AccessError as error:
            return "unavailable", _("검사대기 재고를 조회할 권한이 없습니다: %s",
                                    str(error)[:120]), empty
        except Exception as error:
            # 계약이 바뀌었거나 조회에 실패했다 — 표시를 못 할 뿐, 계획은 돈다.
            _logger.warning("검사대기 수량을 읽지 못했습니다", exc_info=True)
            return "unavailable", _("검사대기 재고를 읽지 못했습니다: %s",
                                    str(error)[:120]), empty
        uom_by_product = {m.id: m.uom_id for m in materials}
        Uom = self.env["uom.uom"]
        result = {}
        for row in rows:
            product_id = row.get("product_id")
            stock_uom = uom_by_product.get(product_id)
            quantity = row.get("quantity", 0.0)
            reserved = row.get("reserved_quantity", 0.0)
            source_uom = Uom.browse(row.get("uom_id")).exists()
            if stock_uom and source_uom and source_uom != stock_uom:
                # 검사 쪽 단위가 자재 재고 단위와 다르면 환산한다(단위 계약 유지).
                quantity = source_uom._compute_quantity(quantity, stock_uom, round=False)
                reserved = source_uom._compute_quantity(reserved, stock_uom, round=False)
            previous = result.get(product_id, (0.0, 0.0))
            result[product_id] = (previous[0] + quantity, previous[1] + reserved)
        return "counted", False, result

    def _stock_on_hand(self, materials):
        """이 계획의 회사에서 **실제로 쓸 수 있는** 재고. {제품: 수량}

        [305 계획 리뷰 (2)] `with_company().qty_available` 은 창고의 **view** 위치
        하위를 센다. 거기에는 IQC 검사대기 같은 internal 형제 위치도 들어간다.
        "IQC 는 자동으로 빠진다" 는 앞선 설명은 틀렸다 — 그렇게 되도록 **범위를 직접
        지정해야** 한다. 여기서는 창고의 재고 위치(Stock) 하위만 센다.

        검사대기 수량을 어떻게 다룰지(재구매 여부)는 정책 문제라 여기서 정하지 않는다.
        지금 하는 것은 '대기 중인 것을 가용으로 세지 않는다' 뿐이다.

        **계획이 재고를 읽는 곳은 전부 이 메서드를 지난다.** 초기 재고·배정 표시·일별
        차트·원재료 소요·발주가 서로 다른 범위를 쓰면 화면의 부족 표시가 발주 수량과
        어긋난다(실제 재현: 화면 available 50 인데 발주는 Stock 10 기준).
        품질 사용 가능 여부는 `_planning_on_hand` 확장점이 정하고, **범위(회사·Stock
        하위)는 여기서** 정한다. (N-PLANNING-IQC-SCOPE)
        """
        self.ensure_one()
        result = defaultdict(float)
        if not materials:
            return result
        result.update(self._planning_on_hand(self._stock_scope(materials)))
        return result

    def _stock_scope(self, products):
        """계획의 **회사**와 창고 **Stock 하위**로 범위를 좁힌 recordset.

        활성 회사가 아니라 계획의 회사다 — 회사 A 계획을 회사 B 에서 열어도 B 의 재고가
        섞이면 안 된다. 그리고 창고 view 하위가 아니라 Stock 하위다 — view 하위에는
        IQC 검사대기 같은 형제 위치가 들어간다.

        `company_owned` 같은 새 context 의미를 만들지 않는다. 위탁·소유 계약은 미확정이다.

        **들어온 `warehouse_id`·`strict` 는 여기서 떼어낸다.** 계획 재고의 범위 계약은
        '계획 회사 창고의 Stock 하위 **전체**' 이고, 그 둘이 남아 있으면 계약이 깨진다.
        (고정 코어 `stock/models/product.py` 기준)
          - `warehouse_id` 가 남으면 `:292~300` 이 그 창고 view 하위와 **교집합**을 낸다.
            회사 B 창고 문맥 + 회사 A Stock → 공집합 → `:314` 이 `FALSE_LEAF` → 가용 0.
          - `strict` 가 남으면 `:321` 이 `location_id in (...)` 정확 일치를 쓴다 →
            Stock **자식 선반**의 재고가 빠진다.
        일반 제품 수량 API 자체와 `owner_id`·LOT·package 의 의미는 건드리지 않는다.
        입력 recordset·context 객체도 바꾸지 않는다 — 정규화한 **사본**을 돌려준다.
        (N-PLANNING-IQC-SCOPE 후속)
        """
        self.ensure_one()
        company = self.company_id or self.env.company
        warehouses = self.env["stock.warehouse"].search(
            [("company_id", "=", company.id)])
        locations = warehouses.mapped("lot_stock_id")
        if not locations:
            # 창고가 없으면 셀 재고도 없다. 기본 범위로 슬쩍 넓히지 않는다.
            return products.browse()
        scoped = products.with_company(company)
        context = {key: value for key, value in scoped.env.context.items()
                   if key not in ("warehouse_id", "strict")}
        context["location"] = locations.ids
        return scoped.with_context(context)

    def _outstanding_ordered_qty(self, materials):
        """이 계획으로 이미 발주했지만 **아직 입고되지 않은** 수량. {제품: (수량, 지연여부)}

        [P1-PP08] 재계획·재계산 때 이 수량을 빼지 않으면 같은 부족분을 다시 발주한다.
        입고가 끝난 몫은 재고에 이미 반영되므로 여기서 세지 않는다.

        **단위를 맞춘다.** 발주는 톤으로, 소요는 kg 으로 잡히는 일이 흔하다. 숫자만
        빼면 1000 배 어긋난다. 발주 라인의 단위를 자재의 재고 단위로 환산해 센다.
        (275 계획 리뷰 (2))

        늦게 도착할 발주도 '이미 발주함' 으로 센다 — 같은 자재를 또 발주해도 더 빨리
        오지 않기 때문이다. 다만 늦는다는 사실은 따로 돌려주어 화면에 남긴다.
        """
        self.ensure_one()
        result = defaultdict(lambda: [0.0, False])
        if not materials:
            return result
        need_dates = {
            req.material_id.id: req.first_need_date
            for req in self.material_requirement_ids
        }
        lines = self.env["purchase.order.line"].search([
            ("order_id.injection_planning_run_id", "=", self.id),
            ("product_id", "in", materials.ids),
            ("order_id.state", "!=", "cancel"),
        ])
        for line in lines:
            pending = (line.product_qty or 0.0) - (line.qty_received or 0.0)
            if pending <= 0:
                continue
            stock_uom = line.product_id.uom_id
            if line.product_uom and stock_uom and line.product_uom != stock_uom:
                pending = line.product_uom._compute_quantity(
                    pending, stock_uom, round=False)
            entry = result[line.product_id.id]
            entry[0] += pending
            need_date = need_dates.get(line.product_id.id)
            planned = line.date_planned
            if need_date and planned and planned.date() > need_date:
                entry[1] = True
        return result

    def action_create_material_po(self):
        """원재료 부족분에 대해 공급업체별 발주서 자동 생성.

        재고가 부족한(is_short) 원재료 중 아직 발주하지 않은 품목을
        공급업체(product.supplierinfo)별로 묶어 발주서를 생성한다.
        공급업체 정보가 없는 품목은 건너뛰고 메시지로 안내한다.
        """
        self.ensure_one()
        self._assert_company_scope()
        if self.state not in ("review", "confirmed"):
            raise UserError(_("검토 또는 확정 상태에서만 발주할 수 있습니다."))
        self._assert_derived_fresh(_("원재료 발주"))
        # 동시 요청이 같은 부족분을 두 번 발주하지 않게 계획 행을 잠근다.
        self._lock_for_mo_generation()
        ledger = self._planning_ledger(("review", "confirmed"))

        # [P1-PP08] '아직 발주 안 했는가' 를 저장된 연결 필드로만 보면 안 된다.
        # 재계산·재검증으로 그 값이 비거나 어긋날 수 있고, 그러면 아직 입고되지 않은
        # 발주를 무시하고 같은 원재료를 다시 발주한다. 실제 발주 잔량에서 판단한다.
        #
        # [275 계획 리뷰 (2)] 부족분도 **계산 당시의 스냅샷(`shortage_qty`)이 아니라
        # 지금 재고**로 다시 본다. 첫 발주 100 중 40 이 이미 품질 해제되어 재고에
        # 들어왔는데 저장된 부족 100 에서 미입고 60 만 빼면 40 을 또 발주한다.
        # 검사 대기 재고는 Stock 하위가 아니므로 `qty_available` 에 애초에 없다 —
        # 여기서 다시 빼지 않는다(이중 차감 금지).
        # [305 계획 리뷰 (3)] 저장된 `is_short` 로 먼저 거르면, 계산 이후 소모되어
        # 지금은 모자란 자재가 검사 자체에서 빠진다. 전 자재를 지금 재고로 다시 본다.
        shortages = self.material_requirement_ids
        materials = shortages.mapped("material_id")
        outstanding = self._outstanding_ordered_qty(materials)
        on_hand = self._stock_on_hand(materials)
        already_covered = self.env["injection.planning.material.requirement"]
        late_covered = self.env["injection.planning.material.requirement"]
        to_order = []
        for req in shortages:
            open_qty, is_late = outstanding.get(req.material_id.id, (0.0, False))
            net = (req.required_qty or 0.0) - on_hand.get(req.material_id.id, 0.0) - open_qty
            if is_late:
                late_covered |= req
            if net <= 0.0:
                if (req.required_qty or 0.0) > on_hand.get(req.material_id.id, 0.0):
                    already_covered |= req      # 재고는 모자라지만 발주로 덮여 있다
                continue
            to_order.append((req, net))
        if not to_order:
            if already_covered:
                detail = ", ".join(already_covered.mapped("material_id.display_name"))
                if late_covered:
                    detail += ("\n⚠ 다만 다음 자재는 필요일보다 늦게 도착 예정입니다: "
                               + ", ".join(late_covered.mapped("material_id.display_name")))
                raise UserError(_(
                    "부족한 원재료는 이미 발주되어 있거나 재고로 충당됩니다: %s", detail))
            raise UserError(_("발주할 부족 원재료가 없습니다."))
        shortages = self.env["injection.planning.material.requirement"].union(
            *[req for req, _net in to_order])
        net_by_material = {req.material_id.id: net for req, net in to_order}

        # 공급업체별로 그룹핑
        by_vendor = defaultdict(list)
        no_vendor = self.env["product.product"]
        for req in shortages:
            seller = req.material_id.seller_ids[:1]
            if not seller:
                no_vendor |= req.material_id
                continue
            by_vendor[seller.partner_id.id].append((req, seller))

        PO = self.env["purchase.order"]
        POLine = self.env["purchase.order.line"]
        created = PO

        for partner_id, items in by_vendor.items():
            # [305 계획 리뷰 (5)] 활성 회사가 아니라 **계획의 회사**로 만든다.
            company = self.company_id or self.env.company
            po = PO.with_company(company).create({
                "partner_id": partner_id,
                "company_id": company.id,
                "injection_planning_run_id": self.id,
                "origin": self.name,
                "date_order": fields.Datetime.now(),
            })
            for req, seller in items:
                # 부족분에서 **미입고 발주 잔량을 뺀 것**만 새로 발주한다.
                order_qty = net_by_material.get(req.material_id.id, req.shortage_qty)
                lead = seller.delay or 0
                date_planned = fields.Datetime.now()
                if req.first_need_date:
                    date_planned = datetime.combine(
                        req.first_need_date - timedelta(days=lead),
                        datetime.min.time(),
                    )
                # [305 계획 리뷰 (4)] 소요는 자재의 재고 단위(kg), 발주는 구매 단위(톤)
                # 인 일이 흔하다. 수치를 그대로 넘기면 1000 배로 발주된다. 단위를 명시하고
                # 수량을 환산하며, 단가도 그 단위 기준으로 맞춘다.
                stock_uom = req.material_id.uom_id
                po_uom = seller.product_uom or req.material_id.uom_po_id or stock_uom
                po_qty = order_qty
                if po_uom and stock_uom and po_uom != stock_uom:
                    po_qty = stock_uom._compute_quantity(order_qty, po_uom, round=False)
                price = seller.price
                if not price:
                    price = req.material_id.standard_price
                    if po_uom and stock_uom and po_uom != stock_uom:
                        # 표준원가는 재고 단위 기준이다. 구매 단위 단가로 환산한다.
                        price = stock_uom._compute_price(price, po_uom)
                POLine.create({
                    "order_id": po.id,
                    "product_id": req.material_id.id,
                    "product_qty": po_qty,
                    "product_uom": po_uom.id if po_uom else False,
                    "price_unit": price,
                    "date_planned": date_planned,
                })
                # [P2] 원재료 소요는 계산 산출물이라 담당자 ACL 은 읽기 전용이다(PP03).
                # 발주 버튼이 마지막 이 write 에서 거절되고 있었다. ACL 을 넓히지 않고
                # 다른 산출물과 같은 제한 권한으로 쓴다 — 버튼의 의도는 유지된다.
                ledger.env["injection.planning.material.requirement"].browse(
                    req.id).write({
                        "purchase_order_id": po.id,
                        "ordered_qty": (req.ordered_qty or 0.0) + order_qty,
                    })
            created |= po

        # SCM 포털 연동 (supplier_portal_purchase 설치 시에만 — 필드 존재 가드):
        # 포털 사용 협력사의 원재료 발주도 외주 발주와 동일하게 포털 노출 + 알림
        if created and "auto_generated" in created._fields:
            for po in created.filtered(lambda p: p.partner_id.is_supplier_portal):
                po.write({"auto_generated": True, "portal_state": "new"})
                po._create_portal_notification("new_po", partner=po.partner_id)

        msg = f"원재료 부족분 발주서 {len(created)}건 생성: {', '.join(created.mapped('name'))}"
        if late_covered:
            msg += ("\n⚠ 이미 발주했지만 **필요일보다 늦게** 도착 예정: "
                    + ", ".join(late_covered.mapped("material_id.display_name"))
                    + " — 추가 발주로는 앞당겨지지 않습니다. 납기를 협의하십시오.")
        if already_covered:
            msg += ("\n· 이미 발주된 미입고 잔량으로 충당되어 제외: "
                    + ", ".join(already_covered.mapped("material_id.display_name")))
        if no_vendor:
            msg += (
                f"\n⚠ 공급업체 미등록으로 발주 제외: "
                f"{', '.join(no_vendor.mapped('display_name'))}"
            )
        self.message_post(body=msg)

        return self.action_view_material_pos()

    def action_view_material_pos(self):
        """생성된 원재료 발주서 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"원재료 발주서 - {self.name}",
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("injection_planning_run_id", "=", self.id)],
        }

    def action_view_daily_summary(self):
        """일별 분석 차트 열기

        차트 모델(SQL View, 언피벗)을 사용하여
        4개 지표(소요량/생산량/재고/안전재고)를 4개 라인으로 동시 표시.
        좌측 searchpanel에서 사출 부품 선택.
        """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"일별 분석 - {self.name}",
            "res_model": "injection.planning.daily.chart",
            "view_mode": "graph,list",
            "domain": [("planning_run_id", "=", self.id)],
        }

    # ─────────────────────────────────────────────
    # Cron 자동 모드
    # ─────────────────────────────────────────────
    @api.model
    def _cron_auto_planning(self):
        """자동 모드: Oracle 수요 → 계획 계산 → MO 생성"""
        config = self.env[
            "injection.planning.config"
        ]._get_active_shift_config()
        if not config or not config.auto_generate_mo:
            return

        today = fields.Date.today()
        plan = self.create({
            "plan_date_from": today,
            "plan_date_to": today + timedelta(days=config.planning_horizon),
        })

        try:
            plan.action_fetch_demand()
            plan.action_calculate_plan()
            if plan._get_mo_candidate_lines():
                plan.generate_manufacturing_orders()
                plan.state = "done"
                _logger.info("자동 생산계획 완료: %s, MO %d건", plan.name, plan.mo_count)
            else:
                plan.state = "done"
                _logger.info("자동 생산계획: 수요 없음, %s", plan.name)
        except Exception:
            _logger.exception("자동 생산계획 실패: %s", plan.name)
            plan.state = "cancelled"
