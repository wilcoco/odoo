import logging
from datetime import date, timedelta

from odoo import fields, models

_logger = logging.getLogger(__name__)


class GenerateDemoWizard(models.TransientModel):
    _name = "injection.generate.demo.wizard"
    _description = "테스트 샘플 데이터 생성"

    plan_start = fields.Date(
        string="계획 시작일",
        default=fields.Date.today,
    )
    plan_days = fields.Integer(
        string="계획 기간 (일)", default=7,
    )
    create_demand = fields.Boolean(
        string="수요 데이터 생성", default=True,
    )
    create_availability = fields.Boolean(
        string="가동 일정 생성", default=True,
    )

    def action_generate(self):
        """샘플 데이터 일괄 생성"""
        self.ensure_one()
        summary = []

        # ── 1. 완제품 4개 (수요 대상) ──
        finished = self._create_finished_products()
        summary.append(f"완제품 {len(finished)}개")

        # ── 2. 사출 부품 6개 (금형으로 생산) ──
        parts = self._create_injection_parts()
        summary.append(f"사출 부품 {len(parts)}개")

        # ── 2-1. 원재료 (수지, 첨가제 등) ──
        raw_materials = self._create_raw_materials()
        summary.append(f"원재료 {len(raw_materials)}개")

        # ── 3. BOM 1단계 (완제품 → 사출 부품) ──
        boms = self._create_boms(finished, parts)
        summary.append(f"BOM 1단계 {len(boms)}개 (완제품→사출부품)")

        # ── 3-1. BOM 2단계 (사출 부품 → 원재료) ──
        boms2 = self._create_part_boms(parts, raw_materials)
        summary.append(f"BOM 2단계 {len(boms2)}개 (사출부품→원재료)")

        # ── 4. 사출기 4대 ──
        workcenters = self._create_workcenters()
        summary.append(f"사출기 {len(workcenters)}대")

        # ── 5. 금형 6개 (사출 부품에 연결) ──
        molds = self._create_molds(parts)
        summary.append(f"금형 {len(molds)}개")

        # ── 6. 사출기-금형 조합 ──
        caps = self._create_capabilities(workcenters, molds)
        summary.append(f"사출기-금형 조합 {len(caps)}개")

        # ── 7. 계획 설정 ──
        config = self._create_config()
        summary.append("계획 설정 1개")

        # ── 7-1. 초기 재고 설정 (사출 부품 + 원재료) ──
        stock_cnt = self._create_initial_stock(parts, raw_materials)
        summary.append(f"초기 재고 {stock_cnt}건")

        # ── 8. 계획 실행 + 수요 + 가동일정 ──
        if self.create_demand or self.create_availability:
            plan_end = self.plan_start + timedelta(days=self.plan_days - 1)
            run = self.env["injection.planning.run"].create({
                "plan_date_from": self.plan_start,
                "plan_date_to": plan_end,
            })

            if self.create_demand:
                demands = self._create_demands(run, finished)
                summary.append(f"수요 {len(demands)}건 (완제품 기준)")

            if self.create_availability:
                avails = self._create_availability(
                    config, workcenters, self.plan_start, plan_end
                )
                summary.append(f"가동 일정 {len(avails)}건")

            summary.append(f"계획 실행 '{run.name}'")

        msg = "샘플 데이터 생성 완료:\n" + "\n".join(f"  - {s}" for s in summary)
        _logger.info(msg)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "샘플 데이터 생성 완료",
                "message": ", ".join(summary),
                "type": "success",
                "sticky": True,
            },
        }

    # ─────────────────────────────────────────────
    # 헬퍼: 제품 생성/조회
    # ─────────────────────────────────────────────
    def _get_or_create_product(self, name, code, storable=True, max_inv=0, min_lot=0):
        Product = self.env["product.product"]
        existing = Product.search([("default_code", "=", code)], limit=1)
        if existing:
            vals = {}
            if max_inv:
                vals["max_inventory_qty"] = max_inv
            if min_lot:
                vals["min_lot_size"] = min_lot
            if vals:
                existing.write(vals)
            return existing
        return Product.create({
            "name": name,
            "default_code": code,
            "type": "consu",
            "is_storable": storable,
            "max_inventory_qty": max_inv,
            "min_lot_size": min_lot,
        })

    # ─────────────────────────────────────────────
    # 1. 완제품 (수요가 들어오는 대상)
    # ─────────────────────────────────────────────
    def _create_finished_products(self):
        """완제품: Oracle 수요에서 오는 제품 코드"""
        specs = [
            # (이름, 코드)
            ("프론트 범퍼 ASSY (SU2)", "86500-BS000EBB"),
            ("리어 범퍼 ASSY (SU2)", "86600-BS000EBB"),
            ("도어트림 LH ASSY (SU2)", "86500-BS000SWP"),
            ("라디에이터 그릴 ASSY (SU2)", "86500-BS020KDG"),
        ]
        products = self.env["product.product"]
        for name, code in specs:
            products |= self._get_or_create_product(name, code, storable=True)
        return products

    # ─────────────────────────────────────────────
    # 2. 사출 부품 (금형으로 만드는 부품)
    # ─────────────────────────────────────────────
    def _create_injection_parts(self):
        """사출 부품: BOM 구성품, 금형에 연결"""
        specs = [
            # (이름, 코드, 최대재고, 최소로트)
            ("프론트 범퍼 쉘", "INJ-BF-001", 5000, 200),
            ("리어 범퍼 쉘", "INJ-BR-001", 5000, 200),
            ("범퍼 브라켓 (공용)", "INJ-BK-001", 10000, 500),
            ("도어트림 패널 LH", "INJ-DT-L01", 4000, 150),
            ("도어트림 클립 (공용)", "INJ-DC-001", 20000, 1000),
            ("라디에이터 그릴 프레임", "INJ-GR-001", 3000, 100),
        ]
        parts = self.env["product.product"]
        for name, code, max_inv, min_lot in specs:
            parts |= self._get_or_create_product(
                name, code, storable=True, max_inv=max_inv, min_lot=min_lot
            )
        return parts

    # ─────────────────────────────────────────────
    # 2-1. 원재료 (수지, 첨가제 등)
    # ─────────────────────────────────────────────
    def _create_raw_materials(self):
        """원재료: 사출 부품 생산에 사용되는 수지/첨가제"""
        specs = [
            # (이름, 코드, UoM은 kg 기준)
            ("PP 수지 (폴리프로필렌)", "RAW-PP-001"),
            ("ABS 수지", "RAW-ABS-001"),
            ("PA66-GF30 (유리섬유 강화 나일론)", "RAW-PA66GF-001"),
            ("POM 수지 (폴리아세탈)", "RAW-POM-001"),
            ("PC+ABS 수지 (블렌드)", "RAW-PCABS-001"),
            ("블랙 마스터배치 (착색제)", "RAW-MB-BK01"),
        ]
        materials = self.env["product.product"]
        for name, code in specs:
            materials |= self._get_or_create_product(name, code, storable=True)
        return materials

    # ─────────────────────────────────────────────
    # 3. BOM 1단계 (완제품 → 사출 부품)
    # ─────────────────────────────────────────────
    def _create_boms(self, finished, parts):
        """
        완제품 BOM 전개:
        프론트 범퍼 ASSY → 프론트 범퍼 쉘 x1 + 범퍼 브라켓 x2
        리어 범퍼 ASSY   → 리어 범퍼 쉘 x1 + 범퍼 브라켓 x2
        도어트림 LH ASSY → 도어트림 패널 LH x1 + 도어트림 클립 x4
        그릴 ASSY        → 그릴 프레임 x1
        """
        BOM = self.env["mrp.bom"]
        fp = {p.default_code: p for p in finished}
        pp = {p.default_code: p for p in parts}

        bom_specs = [
            # (완제품코드, [(사출부품코드, 수량), ...])
            ("86500-BS000EBB", [("INJ-BF-001", 1), ("INJ-BK-001", 2)]),
            ("86600-BS000EBB", [("INJ-BR-001", 1), ("INJ-BK-001", 2)]),
            ("86500-BS000SWP", [("INJ-DT-L01", 1), ("INJ-DC-001", 4)]),
            ("86500-BS020KDG", [("INJ-GR-001", 1)]),
        ]

        created = BOM
        for finished_code, lines in bom_specs:
            finished_product = fp.get(finished_code)
            if not finished_product:
                continue

            # 기존 BOM 확인
            existing = BOM.search([
                ("product_tmpl_id", "=", finished_product.product_tmpl_id.id),
            ], limit=1)
            if existing:
                created |= existing
                continue

            bom_lines = []
            for part_code, qty in lines:
                part = pp.get(part_code)
                if part:
                    bom_lines.append((0, 0, {
                        "product_id": part.id,
                        "product_qty": qty,
                    }))

            if bom_lines:
                created |= BOM.create({
                    "product_tmpl_id": finished_product.product_tmpl_id.id,
                    "product_id": finished_product.id,
                    "product_qty": 1,
                    "type": "normal",
                    "bom_line_ids": bom_lines,
                })
        return created

    # ─────────────────────────────────────────────
    # 3-1. BOM 2단계 (사출 부품 → 원재료)
    # ─────────────────────────────────────────────
    def _create_part_boms(self, parts, raw_materials):
        """
        사출 부품별 원재료 BOM:
        프론트 범퍼 쉘   → PP 수지 2.5kg + 마스터배치 0.05kg
        리어 범퍼 쉘     → PP 수지 2.8kg + 마스터배치 0.06kg
        범퍼 브라켓      → PA66-GF30 0.35kg
        도어트림 패널 LH → ABS 수지 1.8kg + 마스터배치 0.04kg
        도어트림 클립    → POM 수지 0.02kg
        그릴 프레임      → PC+ABS 1.2kg + 마스터배치 0.03kg
        """
        BOM = self.env["mrp.bom"]
        pp = {p.default_code: p for p in parts}
        rm = {r.default_code: r for r in raw_materials}

        part_bom_specs = [
            # (사출부품코드, [(원재료코드, 수량kg), ...])
            ("INJ-BF-001", [("RAW-PP-001", 2.5), ("RAW-MB-BK01", 0.05)]),
            ("INJ-BR-001", [("RAW-PP-001", 2.8), ("RAW-MB-BK01", 0.06)]),
            ("INJ-BK-001", [("RAW-PA66GF-001", 0.35)]),
            ("INJ-DT-L01", [("RAW-ABS-001", 1.8), ("RAW-MB-BK01", 0.04)]),
            ("INJ-DC-001", [("RAW-POM-001", 0.02)]),
            ("INJ-GR-001", [("RAW-PCABS-001", 1.2), ("RAW-MB-BK01", 0.03)]),
        ]

        created = BOM
        for part_code, mat_lines in part_bom_specs:
            part = pp.get(part_code)
            if not part:
                continue

            # 기존 BOM 확인
            existing = BOM.search([
                ("product_tmpl_id", "=", part.product_tmpl_id.id),
            ], limit=1)
            if existing:
                created |= existing
                continue

            bom_lines = []
            for raw_code, qty in mat_lines:
                raw = rm.get(raw_code)
                if raw:
                    bom_lines.append((0, 0, {
                        "product_id": raw.id,
                        "product_qty": qty,
                    }))

            if bom_lines:
                created |= BOM.create({
                    "product_tmpl_id": part.product_tmpl_id.id,
                    "product_id": part.id,
                    "product_qty": 1,
                    "type": "normal",
                    "bom_line_ids": bom_lines,
                })
        return created

    # ─────────────────────────────────────────────
    # 4. 사출기 (작업장)
    # ─────────────────────────────────────────────
    def _create_workcenters(self):
        WC = self.env["mrp.workcenter"]
        specs = [
            ("CC300-01 (3000톤)", "INJ-01"),
            ("CC300-02 (3000톤)", "INJ-02"),
            ("CC200-01 (2000톤)", "INJ-03"),
            ("CC200-02 (2000톤)", "INJ-04"),
        ]
        wcs = WC
        for name, code in specs:
            existing = WC.search([("code", "=", code)], limit=1)
            if existing:
                wcs |= existing
            else:
                wcs |= WC.create({"name": name, "code": code})
        return wcs

    # ─────────────────────────────────────────────
    # 5. 금형 (사출 부품에 연결)
    # ─────────────────────────────────────────────
    def _create_molds(self, parts):
        Mold = self.env["injection.mold"]
        p = {pp.default_code: pp for pp in parts}

        specs = [
            # (name, code, 사출부품코드, cavity, changeover_h, guaranteed, current)
            ("프론트 범퍼 쉘 금형", "MLD-BF-001", "INJ-BF-001", 1, 2.5, 300000, 45000),
            ("리어 범퍼 쉘 금형", "MLD-BR-001", "INJ-BR-001", 1, 2.5, 300000, 52000),
            ("범퍼 브라켓 금형", "MLD-BK-001", "INJ-BK-001", 4, 1.5, 250000, 78000),
            ("도어트림 패널 금형", "MLD-DT-001", "INJ-DT-L01", 1, 2.0, 200000, 30000),
            ("도어트림 클립 금형", "MLD-DC-001", "INJ-DC-001", 8, 1.0, 300000, 15000),
            ("그릴 프레임 금형", "MLD-GR-001", "INJ-GR-001", 1, 1.5, 200000, 10000),
        ]
        molds = Mold
        for name, code, pcode, cavity, co_h, guaranteed, current in specs:
            existing = Mold.search([("code", "=", code)], limit=1)
            if existing:
                molds |= existing
            else:
                product = p.get(pcode)
                molds |= Mold.create({
                    "name": name,
                    "code": code,
                    "product_id": product.id if product else False,
                    "cavity_count": cavity,
                    "changeover_hours": co_h,
                    "guaranteed_shots": guaranteed,
                    "current_shots": current,
                })
        return molds

    # ─────────────────────────────────────────────
    # 6. 사출기-금형 조합
    # ─────────────────────────────────────────────
    def _create_capabilities(self, workcenters, molds):
        Cap = self.env["injection.machine.mold.capability"]
        wc = {w.code: w for w in workcenters}
        md = {m.code: m for m in molds}

        specs = [
            # (wc_code, mold_code, cycle_time, defect_rate, initial_scrap)
            ("INJ-01", "MLD-BF-001", 55.0, 2.0, 15),  # CC300-01 ← 범퍼쉘(전)
            ("INJ-01", "MLD-BR-001", 58.0, 2.5, 15),  # CC300-01 ← 범퍼쉘(후)
            ("INJ-02", "MLD-BF-001", 57.0, 2.0, 15),  # CC300-02 ← 범퍼쉘(전)
            ("INJ-02", "MLD-BK-001", 25.0, 1.5, 10),  # CC300-02 ← 브라켓 (4캐비티)
            ("INJ-03", "MLD-DT-001", 42.0, 1.8, 10),  # CC200-01 ← 도어트림 패널
            ("INJ-03", "MLD-DC-001", 18.0, 1.0, 5),   # CC200-01 ← 도어트림 클립 (8캐비티)
            ("INJ-04", "MLD-GR-001", 38.0, 2.0, 8),   # CC200-02 ← 그릴 프레임
            ("INJ-04", "MLD-BK-001", 28.0, 1.5, 10),  # CC200-02 ← 브라켓 (백업)
        ]
        caps = Cap
        for wc_code, mold_code, ct, dr, scrap in specs:
            w = wc.get(wc_code)
            m = md.get(mold_code)
            if not w or not m:
                continue
            existing = Cap.search([
                ("workcenter_id", "=", w.id),
                ("mold_id", "=", m.id),
            ], limit=1)
            if existing:
                caps |= existing
            else:
                caps |= Cap.create({
                    "workcenter_id": w.id,
                    "mold_id": m.id,
                    "cycle_time": ct,
                    "defect_rate": dr,
                    "initial_scrap": scrap,
                })
        return caps

    # ─────────────────────────────────────────────
    # 7. 계획 설정
    # ─────────────────────────────────────────────
    def _create_config(self):
        Config = self.env["injection.planning.config"]
        config = Config.search([], limit=1)
        if config:
            return config
        return Config.create({
            "planning_horizon": 14,
            "default_changeover": 2.0,
            "default_defect_rate": 2.0,
            "default_initial_scrap": 15,
            "default_min_lot_size": 100,
            "day_shift_hours": 8.0,
            "night_shift_hours": 8.0,
            "day_shift_start": 8.0,
            "night_shift_start": 20.0,
            "safety_stock_days": 3.5,
        })

    # ─────────────────────────────────────────────
    # 7-1. 초기 재고 (사출 부품 + 원재료)
    # ─────────────────────────────────────────────
    def _create_initial_stock(self, parts, raw_materials):
        """
        테스트용 초기 재고 설정 (재고 조정 방식)
        - 사출 부품: 약 2일치 재고
        - 원재료: 약 5일치 재고 (kg 단위)
        """
        Quant = self.env["stock.quant"]
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1,
        )
        if not warehouse:
            return 0
        stock_location = warehouse.lot_stock_id

        # 사출 부품 초기 재고 (약 2일치)
        part_stock = {
            "INJ-BF-001": 300,    # 프론트 범퍼 쉘
            "INJ-BR-001": 250,    # 리어 범퍼 쉘
            "INJ-BK-001": 800,    # 범퍼 브라켓 (공용)
            "INJ-DT-L01": 400,    # 도어트림 패널
            "INJ-DC-001": 1600,   # 도어트림 클립 (공용)
            "INJ-GR-001": 300,    # 그릴 프레임
        }

        # 원재료 초기 재고 (약 5일치, kg)
        raw_stock = {
            "RAW-PP-001": 5000.0,     # PP 수지 5톤
            "RAW-ABS-001": 3000.0,    # ABS 수지 3톤
            "RAW-PA66GF-001": 500.0,  # PA66-GF30 500kg
            "RAW-POM-001": 100.0,     # POM 수지 100kg
            "RAW-PCABS-001": 2000.0,  # PC+ABS 2톤
            "RAW-MB-BK01": 50.0,      # 마스터배치 50kg
        }

        all_products = {p.default_code: p for p in (parts | raw_materials)}
        stock_map = {**part_stock, **raw_stock}
        count = 0

        for code, qty in stock_map.items():
            product = all_products.get(code)
            if not product:
                continue

            # 기존 재고 확인 (이미 재고가 있으면 건너뛰기)
            existing = Quant.search([
                ("product_id", "=", product.id),
                ("location_id", "=", stock_location.id),
            ], limit=1)
            if existing and existing.quantity > 0:
                continue

            # 재고 조정으로 초기 재고 설정
            if existing:
                existing.with_context(inventory_mode=True).write({
                    "inventory_quantity": qty,
                })
                existing.action_apply_inventory()
            else:
                quant = Quant.with_context(inventory_mode=True).create({
                    "product_id": product.id,
                    "location_id": stock_location.id,
                    "inventory_quantity": qty,
                })
                quant.action_apply_inventory()
            count += 1

        return count

    # ─────────────────────────────────────────────
    # 8. 수요 데이터 (완제품 기준)
    # ─────────────────────────────────────────────
    def _create_demands(self, run, finished):
        Demand = self.env["injection.production.demand"]
        p = {pr.default_code: pr for pr in finished}

        # 완제품별 일일 수요 (주말 제외)
        daily_qty = {
            "86500-BS000EBB": [120, 150, 130, 140, 160, 0, 0],  # 프론트 범퍼 ASSY
            "86600-BS000EBB": [100, 130, 110, 120, 140, 0, 0],  # 리어 범퍼 ASSY
            "86500-BS000SWP": [200, 220, 210, 230, 250, 0, 0],  # 도어트림 LH ASSY
            "86500-BS020KDG": [150, 170, 160, 180, 190, 0, 0],  # 그릴 ASSY
        }

        vals_list = []
        for code, week_qty in daily_qty.items():
            product = p.get(code)
            if not product:
                continue
            for day_offset in range(self.plan_days):
                d = self.plan_start + timedelta(days=day_offset)
                qty = week_qty[day_offset % 7]
                if qty <= 0:
                    continue
                vals_list.append({
                    "demand_date": d,
                    "product_id": product.id,
                    "quantity": qty,
                    "demand_type": "daily",
                    "source": "manual",
                    "planning_run_id": run.id,
                })

        if vals_list:
            return Demand.create(vals_list)
        return Demand

    # ─────────────────────────────────────────────
    # 9. 가동 일정
    # ─────────────────────────────────────────────
    def _create_availability(self, config, workcenters, date_from, date_to):
        Avail = self.env["injection.machine.availability"]
        day_h = config.day_shift_hours or 8.0
        night_h = config.night_shift_hours or 8.0

        vals_list = []
        current = date_from
        while current <= date_to:
            weekday = current.weekday()  # 0=월 ~ 6=일
            for wc in workcenters:
                existing = Avail.search([
                    ("workcenter_id", "=", wc.id),
                    ("date", "=", current),
                ], limit=1)
                if existing:
                    continue

                if weekday >= 5:
                    # 주말: 비가동
                    vals_list.append({
                        "workcenter_id": wc.id,
                        "date": current,
                        "day_shift_hours": 0,
                        "night_shift_hours": 0,
                        "unavail_reason": "holiday",
                        "notes": "주말",
                    })
                elif wc.code == "INJ-03" and weekday == 2:
                    # CC200-01 수요일 오후 정비
                    vals_list.append({
                        "workcenter_id": wc.id,
                        "date": current,
                        "day_shift_hours": 4.0,
                        "night_shift_hours": night_h,
                        "unavail_reason": "maintenance",
                        "notes": "수요일 오후 정기 정비",
                    })
                else:
                    vals_list.append({
                        "workcenter_id": wc.id,
                        "date": current,
                        "day_shift_hours": day_h,
                        "night_shift_hours": night_h,
                    })
            current += timedelta(days=1)

        if vals_list:
            return Avail.create(vals_list)
        return Avail
