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

        # ── 1. 제품 8개 ──
        products = self._create_products()
        summary.append(f"제품 {len(products)}개")

        # ── 2. 사출기 (작업장) 4대 ──
        workcenters = self._create_workcenters()
        summary.append(f"사출기 {len(workcenters)}대")

        # ── 3. 금형 6개 ──
        molds = self._create_molds(products)
        summary.append(f"금형 {len(molds)}개")

        # ── 4. 사출기-금형 조합 ──
        caps = self._create_capabilities(workcenters, molds)
        summary.append(f"사출기-금형 조합 {len(caps)}개")

        # ── 5. BOM ──
        boms = self._create_boms(products)
        summary.append(f"BOM {len(boms)}개")

        # ── 6. 계획 설정 ──
        config = self._create_config()
        summary.append("계획 설정 1개")

        # ── 7. 계획 실행 + 수요 + 가동일정 ──
        if self.create_demand or self.create_availability:
            plan_end = self.plan_start + timedelta(days=self.plan_days - 1)
            run = self.env["injection.planning.run"].create({
                "plan_date_from": self.plan_start,
                "plan_date_to": plan_end,
            })

            if self.create_demand:
                demands = self._create_demands(run, products)
                summary.append(f"수요 {len(demands)}건")

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
    # 제품
    # ─────────────────────────────────────────────
    def _create_products(self):
        Product = self.env["product.product"]
        specs = [
            ("프론트 범퍼 (SU2-A)", "86500-BS000EBB", 5000, 200),
            ("리어 범퍼 (SU2-A)", "86600-BS000EBB", 5000, 200),
            ("펜더 LH (SU2-A)", "86500-BS000ISG", 3000, 150),
            ("펜더 RH (SU2-A)", "86500-BS000KDG", 3000, 150),
            ("도어트림 LH (SU2-A)", "86500-BS000SWP", 4000, 100),
            ("도어트림 RH (SU2-A)", "86500-BS020IEG", 4000, 100),
            ("라디에이터 그릴 (SU2-A)", "86500-BS020KDG", 3000, 100),
            ("센터 콘솔 (SU2-A)", "84611-BS000EBB", 2000, 100),
        ]
        products = Product
        for name, code, max_inv, min_lot in specs:
            existing = Product.search([("default_code", "=", code)], limit=1)
            if existing:
                existing.write({
                    "max_inventory_qty": max_inv,
                    "min_lot_size": min_lot,
                })
                products |= existing
            else:
                products |= Product.create({
                    "name": name,
                    "default_code": code,
                    "type": "consu",
                    "is_storable": True,
                    "max_inventory_qty": max_inv,
                    "min_lot_size": min_lot,
                })
        return products

    # ─────────────────────────────────────────────
    # 사출기 (작업장)
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
    # 금형
    # ─────────────────────────────────────────────
    def _create_molds(self, products):
        Mold = self.env["injection.mold"]
        p = {p.default_code: p for p in products}

        specs = [
            # (name, code, product_code, cavity, changeover_h, guaranteed, current)
            ("프론트 범퍼 금형", "MLD-BF-001", "86500-BS000EBB", 1, 2.5, 300000, 45000),
            ("리어 범퍼 금형", "MLD-BR-001", "86600-BS000EBB", 1, 2.5, 300000, 52000),
            ("펜더 공용 금형", "MLD-FD-001", "86500-BS000ISG", 2, 2.0, 250000, 78000),
            ("도어트림 금형", "MLD-DT-001", "86500-BS000SWP", 2, 1.5, 200000, 30000),
            ("라디에이터 그릴 금형", "MLD-GR-001", "86500-BS020KDG", 1, 1.5, 200000, 15000),
            ("센터 콘솔 금형", "MLD-CS-001", "84611-BS000EBB", 1, 2.0, 250000, 10000),
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
    # 사출기-금형 조합
    # ─────────────────────────────────────────────
    def _create_capabilities(self, workcenters, molds):
        Cap = self.env["injection.machine.mold.capability"]
        wc = {w.code: w for w in workcenters}
        md = {m.code: m for m in molds}

        specs = [
            # (wc_code, mold_code, cycle_time, defect_rate, initial_scrap)
            ("INJ-01", "MLD-BF-001", 55.0, 2.0, 15),  # CC300-01 ← 프론트 범퍼
            ("INJ-01", "MLD-BR-001", 58.0, 2.5, 15),  # CC300-01 ← 리어 범퍼
            ("INJ-02", "MLD-BF-001", 57.0, 2.0, 15),  # CC300-02 ← 프론트 범퍼
            ("INJ-02", "MLD-FD-001", 42.0, 1.8, 10),  # CC300-02 ← 펜더
            ("INJ-03", "MLD-DT-001", 38.0, 1.5, 10),  # CC200-01 ← 도어트림
            ("INJ-03", "MLD-GR-001", 35.0, 2.0, 8),   # CC200-01 ← 그릴
            ("INJ-04", "MLD-CS-001", 45.0, 1.5, 12),  # CC200-02 ← 콘솔
            ("INJ-04", "MLD-DT-001", 40.0, 1.8, 10),  # CC200-02 ← 도어트림
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
    # BOM (제품 = 사출 부품, 1:1)
    # ─────────────────────────────────────────────
    def _create_boms(self, products):
        BOM = self.env["mrp.bom"]
        created = BOM
        for product in products:
            existing = BOM.search([
                "|",
                ("product_id", "=", product.id),
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
            ], limit=1)
            if not existing:
                created |= BOM.create({
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "product_id": product.id,
                    "product_qty": 1,
                    "type": "normal",
                })
        return created

    # ─────────────────────────────────────────────
    # 계획 설정
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
    # 수요 데이터 (일별)
    # ─────────────────────────────────────────────
    def _create_demands(self, run, products):
        Demand = self.env["injection.production.demand"]
        p = {pr.default_code: pr for pr in products}

        # 제품별 일일 수요량 (현실적 수치)
        daily_qty = {
            "86500-BS000EBB": [120, 150, 130, 140, 160, 0, 0],   # 프론트 범퍼 (주말 0)
            "86600-BS000EBB": [100, 130, 110, 120, 140, 0, 0],   # 리어 범퍼
            "86500-BS000ISG": [80, 90, 85, 95, 100, 0, 0],       # 펜더 LH
            "86500-BS000KDG": [80, 90, 85, 95, 100, 0, 0],       # 펜더 RH
            "86500-BS000SWP": [200, 220, 210, 230, 250, 0, 0],   # 도어트림 LH
            "86500-BS020IEG": [200, 220, 210, 230, 250, 0, 0],   # 도어트림 RH
            "86500-BS020KDG": [150, 170, 160, 180, 190, 0, 0],   # 그릴
            "84611-BS000EBB": [60, 70, 65, 75, 80, 0, 0],        # 콘솔
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
    # 가동 일정
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
                    # CC200-01 수요일 오후 정비 (주간 4시간만)
                    vals_list.append({
                        "workcenter_id": wc.id,
                        "date": current,
                        "day_shift_hours": 4.0,
                        "night_shift_hours": night_h,
                        "unavail_reason": "maintenance",
                        "notes": "수요일 오후 정기 정비",
                    })
                else:
                    # 정상 가동
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
