import math
import logging
from collections import defaultdict
from markupsafe import Markup
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

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
    notes = fields.Text(string="비고")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    @api.depends(
        "line_ids", "line_ids.planned_qty", "line_ids.changeover_needed", "mo_ids",
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("injection.planning.run")
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

        demands = Demand.search([
            ("demand_date", ">=", self.plan_date_from),
            ("demand_date", "<=", self.plan_date_to),
            ("state", "in", ("draft", "confirmed")),
        ])

        self.demand_ids = [(6, 0, demands.ids)]
        self.message_post(body=_("수요 데이터 %d건 로드") % len(demands))
        return True

    def action_fetch_demand(self):
        """Oracle에서 수요 데이터 로드"""
        self.ensure_one()
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
        config = self._get_config()
        Avail = self.env["injection.machine.availability"]
        workcenters = self.env["mrp.workcenter"].search([])
        if not workcenters:
            raise models.UserError("등록된 사출기(작업장)가 없습니다.")

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
                        "day_shift_hours": config.day_shift_hours or 8.0,
                        "night_shift_hours": config.night_shift_hours or 8.0,
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
        config = self.env["injection.planning.config"].search([], limit=1)
        if not config:
            raise models.UserError("생산계획 설정이 없습니다. 먼저 설정을 생성하세요.")
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
        self.state = "calculating"
        self.line_ids.unlink()

        config = self._get_config()

        # [안전망] 계산 중 '조용한 건너뜀'(미전개·조합없음 등)을 수집해 완료 시 채터 보고
        plan_issues = []
        self = self.with_context(plan_issues=plan_issues)

        def _post_issues():
            if plan_issues:
                self.message_post(body=Markup(
                    "<b>⚠ 계획 계산 경고 %d건</b><br/>" % len(plan_issues)
                    + "<br/>".join("· " + i for i in plan_issues)))

        # 1단계: BOM 전개 (완성품 → 사출 부품)
        part_demands = self._explode_bom()

        if not part_demands:
            self.state = "review"
            self.message_post(body="BOM 전개 결과 사출 부품 수요가 없습니다.")
            _post_issues()
            return

        # 2단계: 순수요 계산 (재고 차감, 최대재고 제한)
        net_demands = self._calculate_net_requirements(part_demands)

        if not net_demands:
            self.state = "review"
            self.message_post(body="현재 재고로 모든 수요 충족 가능. 추가 생산 불필요.")
            _post_issues()
            return

        # 3단계: 사출기 배정 + 수량 조정 + 스케줄링
        lines_data = self._schedule(net_demands, config)

        # 4단계: 계획 라인 생성
        if lines_data:
            self.env["injection.planning.line"].create(lines_data)
            self.message_post(
                body=f"계획 계산 완료: {len(lines_data)}건 라인, "
                     f"총 {sum(d['planned_qty'] for d in lines_data):.0f}개 생산 예정"
            )

        # 5단계: 일별 요약 생성 (차트용)
        self._generate_daily_summary(part_demands, config)

        # 6단계: 원재료 소요/재고 집계 (확정 검토용)
        self._calculate_material_requirements()

        _post_issues()
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
        for c in self.env["injection.machine.mold.capability"].search([("active", "=", True)]):
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
            boms = self.env["mrp.bom"].search([
                "|",
                ("product_id", "=", demand.product_id.id),
                ("product_tmpl_id", "=", demand.product_id.product_tmpl_id.id),
            ])
            bom = boms[:1]
            # [안전망 S4] 같은 품목에 활성 BOM 이 2개 이상이면 임의 선택 상태 — 경고
            if len(boms) > 1 and issues is not None:
                issues.append(
                    "다중 활성 BOM %d개: %s (첫 번째 사용 — ALC/버전 확인 필요)"
                    % (len(boms), demand.product_id.default_code or demand.product_id.name))

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
            for line in bom.bom_line_ids:
                # [G1] 비사출 구성품(외주 체결구·클립 등)은 사출 계획에서 제외
                if not _is_inj(line.product_id):
                    continue
                qty_per = line.product_qty / (bom.product_qty or 1)
                part_demands[(line.product_id.id, str(demand.demand_date))] += (
                    demand.quantity * qty_per
                )

            demand.state = "confirmed"

        return dict(part_demands)

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
        safety_days = int(config.safety_stock_days or 3)

        net = {}
        # 제품별로 재고 한번만 조회
        product_ids = set(pid for pid, _ in part_demands.keys())
        products = self.env["product.product"].browse(list(product_ids))
        max_inv_map = {p.id: p.max_inventory_qty for p in products}

        # running_stock: 생산·소비 모두 반영하는 실시간 재고
        running_stock = {p.id: p.qty_available for p in products}

        for p in products:
            _logger.info(
                "[순수요] 제품 %s (id=%s): qty_available=%.1f, max_inv=%.1f",
                p.default_code, p.id, p.qty_available, max_inv_map.get(p.id, 0),
            )

        # 제품별 일일 풀 캐퍼 계산 (최적 사출기-금형 조합 기준)
        Capability = self.env["injection.machine.mold.capability"]
        capabilities = Capability.search([("active", "=", True)])
        daily_hours = (config.day_shift_hours or 8) + (config.night_shift_hours or 8)

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
                    dr = c.defect_rate or config.default_defect_rate or 0.0
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
            current = running_stock.get(pid, 0)
            max_inv = max_inv_map.get(pid, 0)

            # 향후 N일 안전재고: 다음날부터 N일간 실제 수요 합
            sorted_dates = product_sorted_dates.get(pid, [])
            try:
                idx = sorted_dates.index(date_str)
            except ValueError:
                idx = -1
            future_demand = 0.0
            if idx >= 0:
                for fi in range(1, safety_days + 1):
                    future_idx = idx + fi
                    if future_idx < len(sorted_dates):
                        future_date = sorted_dates[future_idx]
                        future_demand += product_date_demand[pid].get(
                            future_date, 0
                        )

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
        4) 스케줄 종료 시 가동일정에 마지막 금형 기록 (다음 계획용)
        """
        Capability = self.env["injection.machine.mold.capability"]
        Mold = self.env["injection.mold"]
        Avail = self.env["injection.machine.availability"]

        capabilities = Capability.search([("active", "=", True)])
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

        # 기본 교대 시간 (가동일정 미등록 시 사용)
        default_day_h = config.day_shift_hours or 8.0
        default_night_h = config.night_shift_hours or 8.0
        day_start = int(config.day_shift_start or 8)
        night_start = int(config.night_shift_start or 20)
        mo_split_mode = config.mo_split_mode or "none"

        def _get_shift(dt):
            """시간대로 교대 구분"""
            hour = dt.hour
            if day_start <= hour < night_start:
                return "day"
            return "night"

        def _get_shift_end(dt, shift):
            """해당 교대의 종료 시각"""
            if shift == "day":
                return dt.replace(hour=night_start, minute=0, second=0, microsecond=0)
            else:
                # 야간: 다음날 주간 시작
                next_day = dt.date() + timedelta(days=1)
                return datetime.combine(next_day, datetime.min.time()).replace(hour=day_start)

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

        def _find_next_available(wc_id, from_date):
            """가용한 다음 날짜 찾기 (비가동일 건너뛰기)"""
            check = from_date
            plan_end = self.plan_date_to
            while check <= plan_end:
                avail_h, _, _ = _get_available_hours(wc_id, check)
                if avail_h > 0:
                    return check
                check += timedelta(days=1)
            return from_date

        def _order_mold_groups(jobs_by_mold, prev_mold_id):
            """금형 교환 최소화를 위한 그룹 정렬

            전략: 전날 금형과 같은 그룹을 맨 앞에 배치.
            나머지는 작업량이 많은 순서로 배치하여
            큰 작업을 먼저 처리 (교환 후 오래 사용).
            """
            ordered = []
            rest = []
            for mold_id, mold_jobs in jobs_by_mold.items():
                if mold_id == prev_mold_id:
                    # 전날 금형 → 교환 불필요, 최우선
                    ordered.insert(0, (mold_id, mold_jobs))
                else:
                    total_demand = sum(j["demand_qty"] for j in mold_jobs)
                    rest.append((mold_id, mold_jobs, total_demand))
            # 나머지: 작업량 많은 순 (교환 후 오래 쓰는 금형 우선)
            rest.sort(key=lambda x: -x[2])
            for mold_id, mold_jobs, _ in rest:
                ordered.append((mold_id, mold_jobs))
            return ordered

        # ── 작업 배정 [G5 형체력 적합성 + G4 유효능력·부하분산·병렬] ──
        _issues = self.env.context.get("plan_issues")
        assigned_hours = defaultdict(float)  # (wc_id, date_str) → 배정된 시간

        def _eff_cap(c):
            dr = c.defect_rate or config.default_defect_rate or 0.0
            return c.hourly_capacity * max(0.0, 1.0 - dr / 100.0)

        def _suitable_caps(caps_list, pid):
            """[G5] 형체력 적합성: 사출기 형체력 ≥ 금형 요구 형체력.
            둘 중 하나라도 0(미등록)이면 필터 미적용(방어). 전 조합 부적합이면
            경고 후 미필터 진행(생산 자체를 조용히 막지 않기 위함)."""
            ok = []
            for c in caps_list:
                need = c.mold_id.required_clamping_ton or 0.0
                have = c.workcenter_id.x_clamping_force_ton or 0.0
                if need and have and have + 1e-6 < need:
                    continue
                ok.append(c)
            if not ok and caps_list:
                if _issues is not None:
                    _p = self.env["product.product"].browse(pid)
                    _issues.append("형체력 적합 조합 없음(스펙 확인 필요, 미필터 진행): %s"
                                   % (_p.default_code or _p.name))
                return caps_list
            return ok

        for (pid, date_str), demand_qty in sorted(
            net_demands.items(), key=lambda x: (x[0][1], -x[1])  # [G3] 납기순, 동일일자 수량 큰 순
        ):
            caps = product_caps.get(pid, [])
            if not caps:
                _logger.warning("제품 ID %s에 대한 사출기-금형 조합 없음, 건너뜀", pid)
                if _issues is not None:
                    _p = self.env["product.product"].browse(pid)
                    _issues.append("사출기-금형 조합 없음(배정 탈락!): %s %s %.0f개"
                                   % (_p.default_code or _p.name, date_str, demand_qty))
                continue

            # [G4] 유효능력(불량률 반영) 높은 순으로 후보 정렬
            ranked = sorted(_suitable_caps(caps, pid), key=_eff_cap, reverse=True)
            remaining_qty = demand_qty
            for cap in ranked:
                if remaining_qty <= 0:
                    break
                wc = cap.workcenter_id.id
                eff = _eff_cap(cap) or (cap.hourly_capacity or 1.0)
                if cap is ranked[-1]:
                    take = remaining_qty  # 마지막 후보: 잔량 전부(초과분은 시간커서가 익일 이월)
                else:
                    # [G4 부하분산] 이 기계의 당일 잔여 가용시간만큼만 → 넘치면 차선 기계로(병렬)
                    avail_h, _d, _n2 = _get_available_hours(wc, date_str)
                    free_h = avail_h - assigned_hours[(wc, date_str)]
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
        machine_time_cursor = {}
        machine_day_remaining = {}
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
            # 첫 작업: 가용한 첫 날 주간 시작
            if wc_id not in machine_time_cursor:
                first_date = _find_next_available(wc_id, self.plan_date_from)
                start_dt = datetime.combine(
                    first_date, datetime.min.time()
                ).replace(hour=day_start)
                machine_time_cursor[wc_id] = start_dt
                avail_h, _, _ = _get_available_hours(wc_id, first_date)
                machine_day_remaining[wc_id] = avail_h

            for mold_id, mold_jobs in ordered_groups:
                mold = Mold.browse(mold_id)
                # 금형 교환 판단: 현재 장착 금형과 다른 경우
                changeover = (
                    prev_mold_id is not None and prev_mold_id != mold_id
                )
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
                    dr = cap.defect_rate or config.default_defect_rate
                    adjusted = (
                        math.ceil(demand / (1 - dr / 100.0))
                        if dr < 100
                        else demand
                    )

                    # 초기 불량 (그룹 첫 작업 + 금형 교환 시)
                    needs_changeover = changeover and i == 0
                    scrap = (
                        (cap.initial_scrap or config.default_initial_scrap)
                        if needs_changeover
                        else 0
                    )
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

                    co_hours = (
                        mold.changeover_hours or config.default_changeover
                        if needs_changeover
                        else 0.0
                    )

                    # 생산 시간
                    prod_hours = (
                        adjusted / cap.hourly_capacity
                        if cap.hourly_capacity > 0
                        else 0.0
                    )
                    total_job_hours = co_hours + prod_hours

                    # 타임라인: 가동일정 기반 배치
                    cursor = machine_time_cursor[wc_id]
                    remaining = machine_day_remaining.get(wc_id, 0)

                    # 남은 시간 부족 → 다음 가용일로 이동
                    if remaining < total_job_hours:
                        next_date = _find_next_available(
                            wc_id, cursor.date() + timedelta(days=1)
                        )
                        cursor = datetime.combine(
                            next_date, datetime.min.time()
                        ).replace(hour=day_start)
                        avail_h, _, _ = _get_available_hours(
                            wc_id, next_date
                        )
                        remaining = avail_h

                    start_time = cursor
                    end_time = cursor + timedelta(hours=total_job_hours)
                    machine_time_cursor[wc_id] = end_time
                    machine_day_remaining[wc_id] = remaining - total_job_hours

                    # MO 분할 모드에 따라 라인 생성
                    if mo_split_mode == "shift" and cap.hourly_capacity > 0:
                        # 교대별 분할: 교대 경계에서 라인 분리
                        remaining_qty = adjusted
                        remaining_demand = demand
                        seg_start = start_time
                        is_first_seg = True

                        while remaining_qty > 0 and seg_start < end_time:
                            current_shift = _get_shift(seg_start)
                            shift_end = _get_shift_end(seg_start, current_shift)

                            # 이 교대에서 생산 가능한 시간
                            seg_end = min(end_time, shift_end)
                            seg_hours = (seg_end - seg_start).total_seconds() / 3600.0

                            # 교체 시간은 첫 세그먼트에서만 차감
                            if is_first_seg and co_hours > 0:
                                seg_prod_hours = max(0, seg_hours - co_hours)
                            else:
                                seg_prod_hours = seg_hours

                            # 이 세그먼트 생산량
                            seg_qty = math.ceil(seg_prod_hours * cap.hourly_capacity)
                            seg_qty = min(seg_qty, remaining_qty)

                            if seg_qty > 0:
                                # 수요는 비례 배분
                                seg_demand = round(
                                    remaining_demand * seg_qty / remaining_qty, 2
                                ) if remaining_qty > 0 else 0

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
                                    "initial_scrap": scrap if is_first_seg else 0,
                                    "changeover_needed": needs_changeover if is_first_seg else False,
                                    "changeover_hours": co_hours if is_first_seg else 0.0,
                                    "start_time": seg_start,
                                    "end_time": seg_end,
                                    "shift": current_shift,
                                    "current_stock": product.qty_available,
                                    "max_inventory": product.max_inventory_qty,
                                })
                                seq += 10
                                remaining_qty -= seg_qty
                                remaining_demand -= seg_demand

                            seg_start = seg_end
                            is_first_seg = False
                    else:
                        # 분할 없음: 기존 방식
                        lines_data.append({
                            "planning_run_id": self.id,
                            "sequence": seq,
                            "plan_date": job["date_str"],
                            "workcenter_id": wc_id,
                            "mold_id": mold_id,
                            "product_id": job["product_id"],
                            "demand_qty": demand,
                            "planned_qty": adjusted,
                            "defect_rate": dr,
                            "initial_scrap": scrap,
                            "changeover_needed": needs_changeover,
                            "changeover_hours": co_hours,
                            "start_time": start_time,
                            "end_time": end_time,
                            "current_stock": product.qty_available,
                            "max_inventory": product.max_inventory_qty,
                        })
                        seq += 10

            # 스케줄 종료 후 마지막 금형 기록
            machine_current_mold[wc_id] = prev_mold_id

        # 가동일정에 마지막 금형 기록 (다음 계획 시 참조)
        last_plan_date = str(self.plan_date_to)
        for wc_id, last_mold_id in machine_current_mold.items():
            if not last_mold_id:
                continue
            av = avail_map.get((wc_id, last_plan_date))
            if av:
                av.last_mold_id = last_mold_id
            else:
                # 해당 날짜 가동일정 없으면 생성
                Avail.create({
                    "workcenter_id": wc_id,
                    "date": last_plan_date,
                    "last_mold_id": last_mold_id,
                })

        if total_changeovers:
            _logger.info(
                "스케줄링 완료: 총 금형 교환 %d회", total_changeovers
            )

        return lines_data

    # ─────────────────────────────────────────────
    # MO 생성
    # ─────────────────────────────────────────────
    def action_confirm_generate_mo(self):
        """확정 → MO 일괄 생성"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "MO 생성 확인",
            "res_model": "injection.generate.mo.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_planning_run_id": self.id},
        }

    def generate_manufacturing_orders(self):
        """실제 MO 생성"""
        self.ensure_one()
        MO = self.env["mrp.production"]
        created_mos = self.env["mrp.production"]
        failed = []

        for line in self.line_ids.filtered(lambda l: l.state == "draft"):
            bom = self.env["mrp.bom"].search([
                "|",
                ("product_id", "=", line.product_id.id),
                ("product_tmpl_id", "=", line.product_id.product_tmpl_id.id),
            ], limit=1)

            mo_vals = {
                "product_id": line.product_id.id,
                "product_qty": line.planned_qty,
                "bom_id": bom.id if bom else False,
                "date_start": line.start_time or fields.Datetime.now(),
                "planning_run_id": self.id,
            }
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

            try:
                mo = MO.create(mo_vals)
                mo.action_confirm()
                line.write({"mo_id": mo.id, "state": "confirmed"})
                created_mos |= mo
                _logger.info(
                    "MO %s 생성: %s x %s",
                    mo.name, line.product_id.display_name, line.planned_qty,
                )
            except Exception as exc:
                _logger.exception(
                    "MO 생성 실패: product=%s, qty=%s",
                    line.product_id.display_name, line.planned_qty,
                )
                failed.append("%s×%s: %s" % (
                    line.product_id.display_name, line.planned_qty, str(exc)[:80]))

        self.state = "confirmed"
        body = f"{len(created_mos)}건 제조 오더가 생성되었습니다."
        if failed:
            # 조용한 실패 금지 — 생성 실패분을 채터에 각인해 계획 유실을 가시화
            body += "<br/>⚠️ 생성 실패 %d건:<br/>%s" % (len(failed), "<br/>".join(failed))
        self.message_post(body=Markup(body) if failed else body)
        return created_mos

    def action_cancel(self):
        """계획 취소"""
        self.ensure_one()
        self.state = "cancelled"

    def action_reset_draft(self):
        """초안으로 되돌리기"""
        self.ensure_one()
        self.line_ids.unlink()
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
        Summary = self.env["injection.planning.daily.summary"]
        # 기존 요약 삭제
        self.summary_ids.unlink()

        safety_days = config.safety_stock_days or 0.0

        # 1) BOM 전개된 사출부품 수요: part_demands = {(pid, date_str): qty}
        # 제품별 일별 소요량
        demand_by_product_date = defaultdict(lambda: defaultdict(float))
        for (pid, date_str), qty in part_demands.items():
            demand_by_product_date[pid][date_str] += qty

        # 2) 계획 라인에서 제품별 일별 생산량
        planned_by_product_date = defaultdict(lambda: defaultdict(float))
        for line in self.line_ids:
            planned_by_product_date[line.product_id.id][
                str(line.plan_date)
            ] += line.planned_qty

        # 3) 모든 제품 수집
        all_pids = set(demand_by_product_date.keys()) | set(
            planned_by_product_date.keys()
        )
        if not all_pids:
            return

        products = self.env["product.product"].browse(list(all_pids))
        stock_map = {p.id: p.qty_available for p in products}

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
        safety_days = int(config.safety_stock_days or 3)

        # 수요가 있는 날짜만 모아서 향후 N근무일 참조용으로 사용
        # (주말 건너뛰기: 수요 있는 날짜만 카운트)
        all_demand_dates = set()
        for pid in all_pids:
            all_demand_dates.update(demand_by_product_date.get(pid, {}).keys())
            all_demand_dates.update(planned_by_product_date.get(pid, {}).keys())
        # 계획 기간 밖 수요도 포함 (안전재고 참조용)
        demand_sorted = sorted(all_demand_dates)

        def _calc_future_demand(pid, date_str):
            """해당 날짜 다음 근무일부터 N근무일간 실제 수요 합계"""
            future = 0.0
            demands = demand_by_product_date.get(pid, {})
            try:
                idx = demand_sorted.index(date_str)
            except ValueError:
                # 주말 등 수요 없는 날: 다음 수요일부터 참조
                idx = -1
                for i, ds in enumerate(demand_sorted):
                    if ds > date_str:
                        idx = i - 1
                        break
            if idx < 0:
                idx = -1
            count = 0
            fi = 1
            while count < safety_days:
                fi_idx = idx + fi
                if fi_idx >= len(demand_sorted):
                    break
                future += demands.get(demand_sorted[fi_idx], 0)
                fi += 1
                count += 1
            return future

        # 6) 일별 누적 재고 계산 + 레코드 생성
        vals_list = []
        for pid in all_pids:
            running_stock = stock_map.get(pid, 0)
            for date_idx, date_str in enumerate(sorted_dates):
                demand = demand_by_product_date.get(pid, {}).get(date_str, 0)
                planned = planned_by_product_date.get(pid, {}).get(date_str, 0)
                stock_start = running_stock
                stock_end = stock_start + planned - demand
                running_stock = stock_end

                # 향후 N근무일 수요 = 이 날짜에서 확보해야 할 안전재고
                safety_qty = _calc_future_demand(pid, date_str)

                vals_list.append({
                    "planning_run_id": self.id,
                    "product_id": pid,
                    "plan_date": date_str,
                    "demand_qty": demand,
                    "planned_qty": planned,
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
        Req = self.env["injection.planning.material.requirement"]
        Daily = self.env["injection.planning.material.daily"]
        self.material_requirement_ids.unlink()
        self.material_daily_ids.unlink()

        # 원재료별 (날짜→소요량) 집계
        material_date_need = defaultdict(lambda: defaultdict(float))
        for line in self.line_ids:
            if not line.plan_date:
                continue
            bom = self.env["mrp.bom"].search([
                "|",
                ("product_id", "=", line.product_id.id),
                ("product_tmpl_id", "=", line.product_id.product_tmpl_id.id),
            ], limit=1)
            if not bom or not bom.bom_line_ids:
                continue
            for bline in bom.bom_line_ids:
                qty_per = bline.product_qty / (bom.product_qty or 1)
                material_date_need[bline.product_id.id][line.plan_date] += (
                    line.planned_qty * qty_per
                )

        if not material_date_need:
            return

        materials = self.env["product.product"].browse(list(material_date_need.keys()))
        avail_map = {m.id: m.qty_available for m in materials}

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

        Req.create(req_vals)
        Daily.create(daily_vals)

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

    def action_create_material_po(self):
        """원재료 부족분에 대해 공급업체별 발주서 자동 생성.

        재고가 부족한(is_short) 원재료 중 아직 발주하지 않은 품목을
        공급업체(product.supplierinfo)별로 묶어 발주서를 생성한다.
        공급업체 정보가 없는 품목은 건너뛰고 메시지로 안내한다.
        """
        self.ensure_one()
        if self.state not in ("review", "confirmed"):
            raise models.UserError("검토 또는 확정 상태에서만 발주할 수 있습니다.")

        shortages = self.material_requirement_ids.filtered(
            lambda r: r.is_short and not r.purchase_order_id
        )
        if not shortages:
            raise models.UserError("발주할 부족 원재료가 없습니다.")

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
            po = PO.create({
                "partner_id": partner_id,
                "injection_planning_run_id": self.id,
                "origin": self.name,
                "date_order": fields.Datetime.now(),
            })
            for req, seller in items:
                order_qty = req.shortage_qty
                lead = seller.delay or 0
                date_planned = fields.Datetime.now()
                if req.first_need_date:
                    date_planned = datetime.combine(
                        req.first_need_date - timedelta(days=lead),
                        datetime.min.time(),
                    )
                POLine.create({
                    "order_id": po.id,
                    "product_id": req.material_id.id,
                    "product_qty": order_qty,
                    "price_unit": seller.price or req.material_id.standard_price,
                    "date_planned": date_planned,
                })
                req.write({
                    "purchase_order_id": po.id,
                    "ordered_qty": order_qty,
                })
            created |= po

        msg = f"원재료 부족분 발주서 {len(created)}건 생성: {', '.join(created.mapped('name'))}"
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
        config = self.env["injection.planning.config"].search([], limit=1)
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
            if plan.line_ids:
                plan.generate_manufacturing_orders()
                plan.state = "done"
                _logger.info("자동 생산계획 완료: %s, MO %d건", plan.name, plan.mo_count)
            else:
                plan.state = "done"
                _logger.info("자동 생산계획: 수요 없음, %s", plan.name)
        except Exception:
            _logger.exception("자동 생산계획 실패: %s", plan.name)
            plan.state = "cancelled"
