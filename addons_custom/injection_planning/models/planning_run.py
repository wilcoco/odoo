import math
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from odoo import api, fields, models, _

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
    demand_ids = fields.One2many(
        "injection.production.demand", "planning_run_id", string="수요 데이터",
    )
    line_ids = fields.One2many(
        "injection.planning.line", "planning_run_id", string="계획 라인",
    )
    mo_ids = fields.One2many(
        "mrp.production", "planning_run_id", string="생성된 MO",
    )
    mo_count = fields.Integer(compute="_compute_stats", store=True)
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

    @api.depends("line_ids", "line_ids.planned_qty", "line_ids.changeover_needed", "mo_ids")
    def _compute_stats(self):
        for rec in self:
            rec.mo_count = len(rec.mo_ids)
            rec.total_planned_qty = sum(rec.line_ids.mapped("planned_qty"))
            rec.total_changeovers = len(rec.line_ids.filtered("changeover_needed"))

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
    # Oracle 수요 가져오기
    # ─────────────────────────────────────────────
    def action_fetch_demand(self):
        """Oracle에서 수요 데이터 로드"""
        self.ensure_one()
        config = self._get_config()

        try:
            demands = self._fetch_from_oracle(config)
        except Exception as e:
            _logger.exception("Oracle 수요 조회 실패")
            raise models.UserError(f"Oracle 수요 조회 실패: {e}")

        # 기존 Oracle 수요 삭제 후 재로드 (수동 입력은 유지)
        self.demand_ids.filtered(lambda d: d.source == "oracle").unlink()

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
                    "planning_run_id": self.id,
                })
            for (pid, dd, hour), qty in hourly_merged.items():
                create_vals.append({
                    "demand_date": dd,
                    "product_id": pid,
                    "quantity": qty,
                    "demand_type": "hourly",
                    "hour": hour,
                    "source": "oracle",
                    "planning_run_id": self.id,
                })

            self.env["injection.production.demand"].create(create_vals)
            daily_cnt = len(merged)
            hourly_cnt = len(hourly_merged)
            self.message_post(
                body=f"Oracle에서 수요 데이터를 가져왔습니다. "
                     f"(일별 {daily_cnt}건, 시간별 {hourly_cnt}건, "
                     f"총 {sum(d['quantity'] for d in create_vals):.0f}개)"
            )
        else:
            self.message_post(body="Oracle에서 가져온 수요 데이터가 없습니다.")

    def action_add_manual_demand(self):
        """수동 수요 입력 폼 열기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "수요 추가",
            "res_model": "injection.production.demand",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_planning_run_id": self.id,
                "default_source": "manual",
                "default_demand_date": str(self.plan_date_from),
            },
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
        return product

    # ─────────────────────────────────────────────
    # 계획 계산 (스케줄링 엔진)
    # ─────────────────────────────────────────────
    def action_calculate_plan(self):
        """메인 스케줄링 알고리즘"""
        self.ensure_one()
        self.state = "calculating"
        self.line_ids.unlink()

        config = self._get_config()

        # 1단계: BOM 전개 (완성품 → 사출 부품)
        part_demands = self._explode_bom()

        if not part_demands:
            self.state = "review"
            self.message_post(body="BOM 전개 결과 사출 부품 수요가 없습니다.")
            return

        # 2단계: 순수요 계산 (재고 차감, 최대재고 제한)
        net_demands = self._calculate_net_requirements(part_demands)

        if not net_demands:
            self.state = "review"
            self.message_post(body="현재 재고로 모든 수요 충족 가능. 추가 생산 불필요.")
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

        self.state = "review"

    def _explode_bom(self):
        """BOM 전개: 완성품 수요 → 사출 부품별 수요"""
        # {(product_id, date_str): qty}
        part_demands = defaultdict(float)

        for demand in self.demand_ids.filtered(lambda d: d.state == "draft"):
            bom = self.env["mrp.bom"].search([
                "|",
                ("product_id", "=", demand.product_id.id),
                ("product_tmpl_id", "=", demand.product_id.product_tmpl_id.id),
            ], limit=1)

            if not bom:
                # BOM 없으면 제품 자체가 사출품으로 간주
                part_demands[(demand.product_id.id, str(demand.demand_date))] += demand.quantity
                continue

            # BOM 라인에서 사출 부품 추출
            for line in bom.bom_line_ids:
                qty_per = line.product_qty / (bom.product_qty or 1)
                part_demands[(line.product_id.id, str(demand.demand_date))] += (
                    demand.quantity * qty_per
                )

            demand.state = "planned"

        return dict(part_demands)

    def _calculate_net_requirements(self, part_demands):
        """순수요 = 수요 - 현재 재고, 최대 재고 초과분 제외"""
        net = {}
        # 제품별로 재고 한번만 조회
        product_ids = set(pid for pid, _ in part_demands.keys())
        products = self.env["product.product"].browse(list(product_ids))
        stock_map = {p.id: p.qty_available for p in products}
        max_inv_map = {p.id: p.max_inventory_qty for p in products}

        # 날짜순으로 누적 처리
        sorted_keys = sorted(part_demands.keys(), key=lambda k: k[1])
        cumulative_produced = defaultdict(float)

        for (pid, date_str) in sorted_keys:
            required = part_demands[(pid, date_str)]
            current_stock = stock_map.get(pid, 0) + cumulative_produced[pid]
            max_inv = max_inv_map.get(pid, 0)

            shortage = required - current_stock
            if shortage <= 0:
                # 재고 충분
                stock_map[pid] = current_stock - required
                continue

            # 최대 재고 제한
            if max_inv > 0:
                available_space = max_inv - current_stock
                shortage = min(shortage, max(available_space, 0))

            if shortage > 0:
                net[(pid, date_str)] = shortage
                cumulative_produced[pid] += shortage

        return net

    def _schedule(self, net_demands, config):
        """사출기 배정 + 수량 조정 + 금형 교체 최소화 스케줄링"""
        Capability = self.env["injection.machine.mold.capability"]
        Mold = self.env["injection.mold"]

        capabilities = Capability.search([("active", "=", True)])
        if not capabilities:
            raise models.UserError(
                "사출기-금형 조합 설정이 없습니다. 먼저 조합을 등록하세요."
            )

        # 제품 → 가능한 조합 매핑
        product_caps = defaultdict(list)
        for cap in capabilities:
            if cap.product_id:
                product_caps[cap.product_id.id].append(cap)

        # 사출기별 현재 금형 추적 (교체 판단용)
        machine_current_mold = {}

        # 사출기별 작업 수집
        machine_jobs = defaultdict(list)

        for (pid, date_str), demand_qty in sorted(net_demands.items(), key=lambda x: x[1]):
            caps = product_caps.get(pid, [])
            if not caps:
                _logger.warning(
                    "제품 ID %s에 대한 사출기-금형 조합 없음, 건너뜀", pid,
                )
                continue

            # 가장 적합한 조합 선택 (시간당 생산능력 높은 순)
            best_cap = max(caps, key=lambda c: c.hourly_capacity)

            machine_jobs[best_cap.workcenter_id.id].append({
                "product_id": pid,
                "date_str": date_str,
                "demand_qty": demand_qty,
                "capability": best_cap,
            })

        # 사출기별 스케줄링 (같은 금형 연속 배치)
        lines_data = []
        for wc_id, jobs in machine_jobs.items():
            # 금형별로 그룹핑 후 연속 배치 (교체 최소화)
            jobs_by_mold = defaultdict(list)
            for job in jobs:
                jobs_by_mold[job["capability"].mold_id.id].append(job)

            seq = 10
            for mold_id, mold_jobs in jobs_by_mold.items():
                mold = Mold.browse(mold_id)
                # 금형 교체 판단
                prev_mold = machine_current_mold.get(wc_id)
                changeover = prev_mold is not None and prev_mold != mold_id
                machine_current_mold[wc_id] = mold_id

                for i, job in enumerate(mold_jobs):
                    cap = job["capability"]
                    demand = job["demand_qty"]

                    # 불량율 반영
                    dr = cap.defect_rate or config.default_defect_rate
                    adjusted = math.ceil(demand / (1 - dr / 100.0)) if dr < 100 else demand

                    # 초기 불량 (첫 번째 작업 + 금형 교체 시에만)
                    needs_changeover = changeover and i == 0
                    scrap = (cap.initial_scrap or config.default_initial_scrap) if needs_changeover else 0
                    adjusted += scrap

                    # 최소 로트
                    product = self.env["product.product"].browse(job["product_id"])
                    min_lot = product.min_lot_size or config.default_min_lot_size
                    if min_lot > 0 and adjusted < min_lot:
                        adjusted = min_lot

                    co_hours = mold.changeover_hours or config.default_changeover if needs_changeover else 0.0

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
                        "current_stock": product.qty_available,
                        "max_inventory": product.max_inventory_qty,
                    })
                    seq += 10

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

            try:
                mo = MO.create(mo_vals)
                mo.action_confirm()
                line.write({"mo_id": mo.id, "state": "confirmed"})
                created_mos |= mo
                _logger.info(
                    "MO %s 생성: %s x %s",
                    mo.name, line.product_id.display_name, line.planned_qty,
                )
            except Exception:
                _logger.exception(
                    "MO 생성 실패: product=%s, qty=%s",
                    line.product_id.display_name, line.planned_qty,
                )

        self.state = "confirmed"
        self.message_post(
            body=f"{len(created_mos)}건 제조 오더가 생성되었습니다."
        )
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
