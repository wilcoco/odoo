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
        string="계획 기간 (일)", default=14,
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

        # ── 1. 완제품 6개 (수요 대상, 컬러별) ──
        finished = self._create_finished_products()
        summary.append(f"완제품 {len(finished)}개 (컬러별)")

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

        # ── 7-1. 공급업체 + 구매가격 + 제품 원가 설정 ──
        vendor_cnt = self._create_vendors_and_costs(
            finished, parts, raw_materials
        )
        summary.append(f"공급업체/원가 {vendor_cnt}건")

        # ── 7-2. 초기 재고 설정 (사출 부품 + 원재료) ──
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

            # ── 9. 자동 계획 계산 (일별 요약 데이터 생성) ──
            if self.create_demand and run.demand_ids:
                run.action_calculate_plan()
                summary.append(
                    f"계획 계산 완료 (라인 {len(run.line_ids)}건, "
                    f"일별 요약 {len(run.summary_ids)}건)"
                )

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
        """완제품: Oracle 수요에서 오는 제품 코드

        품번 구조: XXXXX-XXXXXYYY
          - XXXXX-XXXXX = 사출 기준코드 (injection_base_code)
          - YYY = 도장 컬러코드 (사출과 무관)
        같은 기준코드 → 같은 사출 부품(BOM) 공유
        """
        specs = [
            # (이름, 코드, 사출기준코드)
            # ── 프론트 범퍼 (86500-BS000) 컬러 2종 → 같은 사출 BOM ──
            ("프론트 범퍼 ASSY (에보니블랙)", "86500-BS000EBB", "86500-BS000"),
            ("프론트 범퍼 ASSY (스노우화이트)", "86500-BS000SWP", "86500-BS000"),
            # ── 리어 범퍼 (86600-BS000) 컬러 2종 → 같은 사출 BOM ──
            ("리어 범퍼 ASSY (에보니블랙)", "86600-BS000EBB", "86600-BS000"),
            ("리어 범퍼 ASSY (카키그린)", "86600-BS000KDG", "86600-BS000"),
            # ── 도어트림 (82310-BS000) ──
            ("도어트림 LH ASSY (에보니블랙)", "82310-BS000EBB", "82310-BS000"),
            # ── 라디에이터 그릴 (86500-BS020) ──
            ("라디에이터 그릴 ASSY (크롬)", "86500-BS020CRM", "86500-BS020"),
        ]
        products = self.env["product.product"]
        for name, code, base_code in specs:
            p = self._get_or_create_product(name, code, storable=True)
            if p.injection_base_code != base_code:
                p.injection_base_code = base_code
            products |= p
        return products

    # ─────────────────────────────────────────────
    # 2. 사출 부품 (금형으로 만드는 부품)
    # ─────────────────────────────────────────────
    def _create_injection_parts(self):
        """사출 부품: BOM 구성품, 금형에 연결"""
        specs = [
            # (이름, 코드, 최대재고, 최소로트)
            # 최대재고 ≈ 5일치 수요, 최소로트 = 현실적 배치 단위
            ("프론트 범퍼 쉘", "INJ-BF-001", 2500, 200),
            ("리어 범퍼 쉘", "INJ-BR-001", 1500, 200),
            ("프론트 범퍼 브라켓", "INJ-BK-F01", 5000, 500),
            ("리어 범퍼 브라켓", "INJ-BK-R01", 3000, 500),
            ("도어트림 패널 LH", "INJ-DT-L01", 4000, 200),
            ("도어트림 클립", "INJ-DC-001", 16000, 1000),
            ("라디에이터 그릴 프레임", "INJ-GR-001", 5000, 200),
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
        완제품 BOM: 같은 기준코드(앞자리)의 컬러 변종 → 같은 사출 부품
        86500-BS000EBB (프론트 범퍼 블랙)  → 프론트 쉘 x1 + 프론트 브라켓 x2
        86500-BS000SWP (프론트 범퍼 화이트) → 프론트 쉘 x1 + 프론트 브라켓 x2  ← 같은 사출품!
        86600-BS000EBB (리어 범퍼 블랙)    → 리어 쉘 x1 + 리어 브라켓 x2
        86600-BS000KDG (리어 범퍼 그린)    → 리어 쉘 x1 + 리어 브라켓 x2  ← 같은 사출품!
        82310-BS000EBB (도어트림)          → 패널 x1 + 클립 x4
        86500-BS020CRM (그릴)              → 프레임 x1
        """
        BOM = self.env["mrp.bom"]
        fp = {p.default_code: p for p in finished}
        pp = {p.default_code: p for p in parts}

        bom_specs = [
            # (완제품코드, [(사출부품코드, 수량), ...])
            # 컬러 다른 제품도 각각 BOM 생성 → 같은 사출 부품
            ("86500-BS000EBB", [("INJ-BF-001", 1), ("INJ-BK-F01", 2)]),  # 프론트 범퍼 블랙
            ("86500-BS000SWP", [("INJ-BF-001", 1), ("INJ-BK-F01", 2)]),  # 프론트 범퍼 화이트
            ("86600-BS000EBB", [("INJ-BR-001", 1), ("INJ-BK-R01", 2)]),  # 리어 범퍼 블랙
            ("86600-BS000KDG", [("INJ-BR-001", 1), ("INJ-BK-R01", 2)]),  # 리어 범퍼 그린
            ("82310-BS000EBB", [("INJ-DT-L01", 1), ("INJ-DC-001", 4)]),  # 도어트림
            ("86500-BS020CRM", [("INJ-GR-001", 1)]),                     # 그릴
        ]

        created = BOM
        for finished_code, lines in bom_specs:
            finished_product = fp.get(finished_code)
            if not finished_product:
                continue

            # 기존 BOM 삭제 후 재생성 (데이터 갱신 보장)
            existing = BOM.search([
                ("product_tmpl_id", "=", finished_product.product_tmpl_id.id),
            ])
            if existing:
                existing.unlink()

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
        프론트 범퍼 쉘     → PP 수지 2.5kg + 마스터배치 0.05kg
        리어 범퍼 쉘       → PP 수지 2.8kg + 마스터배치 0.06kg
        프론트 범퍼 브라켓 → PA66-GF30 0.35kg
        리어 범퍼 브라켓   → PA66-GF30 0.40kg
        도어트림 패널 LH   → ABS 수지 1.8kg + 마스터배치 0.04kg
        도어트림 클립      → POM 수지 0.02kg
        그릴 프레임        → PC+ABS 1.2kg + 마스터배치 0.03kg
        """
        BOM = self.env["mrp.bom"]
        pp = {p.default_code: p for p in parts}
        rm = {r.default_code: r for r in raw_materials}

        part_bom_specs = [
            # (사출부품코드, [(원재료코드, 수량kg), ...])
            ("INJ-BF-001", [("RAW-PP-001", 2.5), ("RAW-MB-BK01", 0.05)]),
            ("INJ-BR-001", [("RAW-PP-001", 2.8), ("RAW-MB-BK01", 0.06)]),
            ("INJ-BK-F01", [("RAW-PA66GF-001", 0.35)]),
            ("INJ-BK-R01", [("RAW-PA66GF-001", 0.40)]),
            ("INJ-DT-L01", [("RAW-ABS-001", 1.8), ("RAW-MB-BK01", 0.04)]),
            ("INJ-DC-001", [("RAW-POM-001", 0.02)]),
            ("INJ-GR-001", [("RAW-PCABS-001", 1.2), ("RAW-MB-BK01", 0.03)]),
        ]

        created = BOM
        for part_code, mat_lines in part_bom_specs:
            part = pp.get(part_code)
            if not part:
                continue

            # 기존 BOM 삭제 후 재생성 (데이터 갱신 보장)
            existing = BOM.search([
                ("product_tmpl_id", "=", part.product_tmpl_id.id),
            ])
            if existing:
                existing.unlink()

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
            ("프론트 범퍼 브라켓 금형", "MLD-BK-F01", "INJ-BK-F01", 4, 1.5, 250000, 78000),
            ("리어 범퍼 브라켓 금형", "MLD-BK-R01", "INJ-BK-R01", 4, 1.5, 250000, 65000),
            ("도어트림 패널 금형", "MLD-DT-001", "INJ-DT-L01", 1, 2.0, 200000, 30000),
            ("도어트림 클립 금형", "MLD-DC-001", "INJ-DC-001", 8, 1.0, 300000, 15000),
            ("그릴 프레임 금형", "MLD-GR-001", "INJ-GR-001", 1, 1.5, 200000, 10000),
        ]
        molds = Mold
        for name, code, pcode, cavity, co_h, guaranteed, current in specs:
            product = p.get(pcode)
            vals = {
                "name": name,
                "code": code,
                "product_id": product.id if product else False,
                "cavity_count": cavity,
                "changeover_hours": co_h,
                "guaranteed_shots": guaranteed,
                "current_shots": current,
            }
            existing = Mold.search([("code", "=", code)], limit=1)
            if existing:
                # 항상 최신 값으로 업데이트 (product_id 누락 방지)
                existing.write(vals)
                molds |= existing
            else:
                molds |= Mold.create(vals)
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
            ("INJ-01", "MLD-BF-001", 55.0, 2.0, 15),   # CC300-01 ← 프론트 범퍼쉘
            ("INJ-01", "MLD-BR-001", 58.0, 2.5, 15),   # CC300-01 ← 리어 범퍼쉘
            ("INJ-02", "MLD-BF-001", 57.0, 2.0, 15),   # CC300-02 ← 프론트 범퍼쉘 (백업)
            ("INJ-02", "MLD-BK-F01", 25.0, 1.5, 10),   # CC300-02 ← 프론트 브라켓 (4캐비티)
            ("INJ-02", "MLD-BK-R01", 26.0, 1.5, 10),   # CC300-02 ← 리어 브라켓 (4캐비티)
            ("INJ-03", "MLD-DT-001", 42.0, 1.8, 10),   # CC200-01 ← 도어트림 패널
            ("INJ-03", "MLD-DC-001", 18.0, 1.0, 5),    # CC200-01 ← 도어트림 클립 (8캐비티)
            ("INJ-04", "MLD-GR-001", 38.0, 2.0, 8),    # CC200-02 ← 그릴 프레임
            ("INJ-04", "MLD-BK-R01", 28.0, 1.5, 10),   # CC200-02 ← 리어 브라켓 (백업)
        ]
        caps = Cap
        for wc_code, mold_code, ct, dr, scrap in specs:
            w = wc.get(wc_code)
            m = md.get(mold_code)
            if not w or not m:
                continue
            vals = {
                "workcenter_id": w.id,
                "mold_id": m.id,
                "cycle_time": ct,
                "defect_rate": dr,
                "initial_scrap": scrap,
            }
            existing = Cap.search([
                ("workcenter_id", "=", w.id),
                ("mold_id", "=", m.id),
            ], limit=1)
            if existing:
                # 항상 최신 값으로 업데이트 (stored related 필드 재계산 유도)
                existing.write(vals)
                caps |= existing
            else:
                caps |= Cap.create(vals)
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
            "safety_stock_days": 3,
        })

    # ─────────────────────────────────────────────
    # 7-1. 공급업체 + 구매가격 + 제품 원가
    # ─────────────────────────────────────────────
    def _create_vendors_and_costs(self, finished, parts, raw_materials):
        """
        공급업체 등록 + 원재료 구매가격(supplierinfo) + 전 제품 원가 설정
        MO 완료 시 자동 분개에 필요:
          - 원재료 출고 → standard_price 기준 분개
          - 완성품 입고 → standard_price 기준 분개
        """
        Partner = self.env["res.partner"]
        SupplierInfo = self.env["product.supplierinfo"]
        count = 0

        # ── 공급업체 3곳 생성 ──
        vendor_specs = [
            {
                "name": "(주)한국폴리머",
                "ref": "VND-POLY-001",
                "company_type": "company",
                "supplier_rank": 1,
                "phone": "031-555-1001",
                "email": "order@koreapoly.co.kr",
            },
            {
                "name": "(주)대한수지",
                "ref": "VND-RESIN-001",
                "company_type": "company",
                "supplier_rank": 1,
                "phone": "031-555-2002",
                "email": "sales@dhresin.co.kr",
            },
            {
                "name": "(주)컬러텍",
                "ref": "VND-COLOR-001",
                "company_type": "company",
                "supplier_rank": 1,
                "phone": "031-555-3003",
                "email": "info@colortech.co.kr",
            },
        ]
        vendors = {}
        for spec in vendor_specs:
            existing = Partner.search([("ref", "=", spec["ref"])], limit=1)
            if existing:
                vendors[spec["ref"]] = existing
            else:
                vendors[spec["ref"]] = Partner.create(spec)
                count += 1

        # ── 원재료별 공급업체 + 구매가격 (product.supplierinfo) ──
        rm = {r.default_code: r for r in raw_materials}
        supplier_price_specs = [
            # (원재료코드, 공급업체ref, 구매가격(원/단위), 최소수량, 리드타임)
            ("RAW-PP-001", "VND-POLY-001", 1500.0, 500, 3),
            ("RAW-PP-001", "VND-RESIN-001", 1550.0, 1000, 5),   # 대체 공급
            ("RAW-ABS-001", "VND-POLY-001", 2500.0, 300, 3),
            ("RAW-PA66GF-001", "VND-RESIN-001", 5000.0, 100, 7),
            ("RAW-POM-001", "VND-RESIN-001", 3500.0, 50, 5),
            ("RAW-PCABS-001", "VND-POLY-001", 3800.0, 200, 4),
            ("RAW-MB-BK01", "VND-COLOR-001", 8000.0, 25, 2),
        ]

        for raw_code, vendor_ref, price, min_qty, delay in supplier_price_specs:
            product = rm.get(raw_code)
            vendor = vendors.get(vendor_ref)
            if not product or not vendor:
                continue
            existing = SupplierInfo.search([
                ("partner_id", "=", vendor.id),
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
            ], limit=1)
            if not existing:
                SupplierInfo.create({
                    "partner_id": vendor.id,
                    "product_tmpl_id": product.product_tmpl_id.id,
                    "price": price,
                    "min_qty": min_qty,
                    "delay": delay,
                })
                count += 1

        # ── 전 제품 원가 (standard_price) 설정 ──
        # 원재료 원가 = 구매가격 기준
        raw_costs = {
            "RAW-PP-001": 1500.0,       # PP ₩1,500/kg
            "RAW-ABS-001": 2500.0,      # ABS ₩2,500/kg
            "RAW-PA66GF-001": 5000.0,   # PA66-GF30 ₩5,000/kg
            "RAW-POM-001": 3500.0,      # POM ₩3,500/kg
            "RAW-PCABS-001": 3800.0,    # PC+ABS ₩3,800/kg
            "RAW-MB-BK01": 8000.0,      # 마스터배치 ₩8,000/kg
        }
        # 사출 부품 원가 = 원재료비 + 가공비
        part_costs = {
            "INJ-BF-001": 5500.0,   # PP 2.5kg(3,750) + 가공비
            "INJ-BR-001": 6000.0,   # PP 2.8kg(4,200) + 가공비
            "INJ-BK-F01": 2800.0,   # PA66 0.35kg(1,750) + 가공비
            "INJ-BK-R01": 3100.0,   # PA66 0.40kg(2,000) + 가공비
            "INJ-DT-L01": 6500.0,   # ABS 1.8kg(4,500) + 가공비
            "INJ-DC-001": 250.0,    # POM 0.02kg(70) + 가공비
            "INJ-GR-001": 6200.0,   # PCABS 1.2kg(4,560) + 가공비
        }
        # 완제품 원가 = BOM 구성품 합산 (컬러 무관, 사출 원가 동일)
        finished_costs = {
            "86500-BS000EBB": 11100.0,  # 프론트 범퍼: 쉘(5,500) + 프론트브라켓x2(5,600)
            "86500-BS000SWP": 11100.0,  # 프론트 범퍼: 같은 사출 원가
            "86600-BS000EBB": 12200.0,  # 리어 범퍼: 쉘(6,000) + 리어브라켓x2(6,200)
            "86600-BS000KDG": 12200.0,  # 리어 범퍼: 같은 사출 원가
            "82310-BS000EBB": 7500.0,   # 도어트림: 패널(6,500) + 클립x4(1,000)
            "86500-BS020CRM": 6200.0,   # 그릴: 프레임(6,200)
        }

        all_costs = {**raw_costs, **part_costs, **finished_costs}
        all_products = {
            p.default_code: p
            for p in (finished | parts | raw_materials)
        }

        for code, cost in all_costs.items():
            product = all_products.get(code)
            if product and product.standard_price != cost:
                product.standard_price = cost
                count += 1

        return count

    # ─────────────────────────────────────────────
    # 7-2. 초기 재고 (사출 부품 + 원재료)
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

        # 사출 부품 초기 재고 (안전재고 3일치의 80%)
        # 안전재고 = 일수요 × 3일, 초기재고 = 안전재고 × 0.8
        part_stock = {
            "INJ-BF-001": 1044,   # 435/일 × 3 × 0.8 = 1,044
            "INJ-BR-001": 686,    # 286/일 × 3 × 0.8 = 686
            "INJ-BK-F01": 2088,   # 870/일 × 3 × 0.8 = 2,088
            "INJ-BK-R01": 1373,   # 572/일 × 3 × 0.8 = 1,373
            "INJ-DT-L01": 1872,   # 780/일 × 3 × 0.8 = 1,872
            "INJ-DC-001": 7488,   # 3120/일 × 3 × 0.8 = 7,488
            "INJ-GR-001": 2477,   # 1032/일 × 3 × 0.8 = 2,477
        }

        # 원재료 초기 재고 (약 12일치, kg) — 계획기간(10근무일) 충분히 커버
        raw_stock = {
            "RAW-PP-001": 24000.0,    # PP 수지 24톤 (일소모 ~1.9톤)
            "RAW-ABS-001": 17000.0,   # ABS 수지 17톤 (일소모 ~1.4톤)
            "RAW-PA66GF-001": 6500.0, # PA66-GF30 6.5톤 (일소모 ~530kg)
            "RAW-POM-001": 800.0,     # POM 수지 800kg (일소모 ~62kg)
            "RAW-PCABS-001": 15000.0, # PC+ABS 15톤 (일소모 ~1.2톤)
            "RAW-MB-BK01": 1300.0,    # 마스터배치 1.3톤 (일소모 ~100kg)
        }

        all_products = {p.default_code: p for p in (parts | raw_materials)}
        stock_map = {**part_stock, **raw_stock}
        count = 0

        for code, qty in stock_map.items():
            product = all_products.get(code)
            if not product:
                continue

            # 기존 재고 quant 있으면 목표 수량으로 리셋
            # (샘플 재생성 시 항상 동일한 초기 재고로 설정)
            existing = Quant.search([
                ("product_id", "=", product.id),
                ("location_id", "=", stock_location.id),
            ], limit=1)

            if existing:
                existing.with_context(inventory_mode=True).write({
                    "inventory_quantity": qty,   # 누적이 아닌 고정값
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

        # 완제품별 일일 수요 (주말 제외, 7일 주기로 반복)
        # 같은 기준코드의 컬러별 수요가 따로 들어옴 → BOM 전개 시 합산됨
        #
        # 가동률 목표:
        #   INJ-01 (BF+BR 쉘): 84%  ← 금형 교환 2.5h 포함, 타이트
        #   INJ-02 (브라켓):   25%  ← 4캐비티 금형으로 빠르게 생산
        #   INJ-03 (DT+DC):    75%  ← 교환 1h 포함
        #   INJ-04 (그릴):     68%
        daily_qty = {
            # ── 프론트 범퍼 (BOM: 쉘 x1 + 브라켓 x2) ──
            # 합산 ~435/일 → INJ-01에서 6.6h, 브라켓 870/일 → INJ-02에서 1.5h
            "86500-BS000EBB": [270, 290, 260, 280, 300, 0, 0],   # 에보니블랙 ~280
            "86500-BS000SWP": [150, 160, 140, 155, 170, 0, 0],   # 스노우화이트 ~155
            # ── 리어 범퍼 (BOM: 쉘 x1 + 브라켓 x2) ──
            # 합산 ~286/일 → INJ-01에서 4.6h, 브라켓 572/일 → INJ-02에서 1.0h
            "86600-BS000EBB": [180, 195, 170, 185, 200, 0, 0],   # 에보니블랙 ~186
            "86600-BS000KDG": [95, 105, 90, 100, 110, 0, 0],     # 카키그린 ~100
            # ── 도어트림 (BOM: 패널 x1 + 클립 x4) ──
            # 패널 ~780/일 → INJ-03에서 9.1h, 클립 3120/일 → INJ-03에서 2.0h
            "82310-BS000EBB": [750, 800, 720, 780, 850, 0, 0],   # 도어트림 LH ~780
            # ── 라디에이터 그릴 (BOM: 프레임 x1) ──
            # ~1032/일 → INJ-04에서 10.9h
            "86500-BS020CRM": [1000, 1080, 960, 1020, 1100, 0, 0], # 그릴 ~1032
        }

        # 수요 기간 = 계획 기간 + 7일 (안전재고 참조용 향후 수요)
        # 계획 마지막 날에도 향후 3일 수요가 존재해야 안전재고 계산 가능
        demand_days = self.plan_days + 7

        vals_list = []
        for code, week_qty in daily_qty.items():
            product = p.get(code)
            if not product:
                continue
            for day_offset in range(demand_days):
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
