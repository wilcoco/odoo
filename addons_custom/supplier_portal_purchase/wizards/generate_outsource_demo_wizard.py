import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class GenerateOutsourceDemoWizard(models.TransientModel):
    """외주 부품 샘플 데이터 생성 (기존 BOM에 외주 부품 추가)"""
    _name = "supplier.generate.outsource.demo.wizard"
    _description = "외주 부품 샘플 데이터 생성"

    add_to_existing_bom = fields.Boolean(
        string="기존 BOM에 외주 부품 추가",
        default=True,
    )
    create_test_product = fields.Boolean(
        string="테스트용 신규 제품 생성",
        default=False,
        help="새로운 완제품 + 외주부품 + BOM + 수요 데이터 생성",
    )
    create_supply_chain = fields.Boolean(
        string="다단계 공급망 테스트",
        default=False,
        help="2단계 공급망 (1차→2차→우리회사) 테스트 데이터 생성",
    )

    def action_generate(self):
        """외주 샘플 데이터 생성"""
        self.ensure_one()
        summary = []

        # 1. 협력사 생성 (이미 데모 데이터로 로드되었을 수 있음)
        partners = self._create_suppliers()
        summary.append(f"협력사 {len(partners)}개")

        # 2. 외주 부품 생성
        outsource_products = self._create_outsource_products(partners)
        summary.append(f"외주 부품 {len(outsource_products)}개")

        # 3. 기존 BOM에 외주 부품 추가
        if self.add_to_existing_bom:
            bom_lines = self._add_outsource_to_boms(outsource_products)
            summary.append(f"BOM 라인 {bom_lines}개 추가")

        # 4. 테스트용 신규 제품 생성
        if self.create_test_product:
            test_result = self._create_test_product_set(partners)
            summary.append(test_result)

        # 5. 다단계 공급망 테스트 데이터
        if self.create_supply_chain:
            chain_result = self._create_supply_chain_test(partners)
            summary.append(chain_result)

        # 6. 계획 설정 업데이트 (자동 발주 활성화)
        self._update_config()
        summary.append("외주 자동발주 설정 활성화")

        msg = "외주 샘플 데이터 생성 완료:\n" + "\n".join(f"  - {s}" for s in summary)
        _logger.info(msg)

        # 알림 표시 후 창 닫기
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "외주 샘플 데이터 생성 완료",
                "message": ", ".join(summary),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _create_suppliers(self):
        """협력사 생성 (이미 있으면 업데이트)"""
        Partner = self.env["res.partner"]
        suppliers = Partner

        specs = [
            {
                "name": "(주)한국브라켓",
                "email": "contact@hanbracket.co.kr",
                "phone": "02-1234-5678",
                "is_supplier_portal": True,
                "supplier_portal_token": "demo_token_hanbracket_2026",
                "supplier_rank": 1,
            },
            {
                "name": "대한하우징(주)",
                "email": "contact@dhhousing.co.kr",
                "phone": "031-9876-5432",
                "is_supplier_portal": True,
                "supplier_portal_token": "demo_token_dhhousing_2026",
                "supplier_rank": 1,
            },
            {
                "name": "삼성캡(주)",
                "email": "contact@sscap.co.kr",
                "phone": "032-5555-6666",
                "is_supplier_portal": True,
                "supplier_portal_token": "demo_token_sscap_2026",
                "supplier_rank": 1,
            },
        ]

        for vals in specs:
            existing = Partner.search([("name", "=", vals["name"])], limit=1)
            if existing:
                existing.write(vals)
                suppliers |= existing
            else:
                suppliers |= Partner.create(vals)

        return suppliers

    def _create_outsource_products(self, partners):
        """외주 부품 생성"""
        Product = self.env["product.product"]
        products = Product

        # 협력사별 제품 매핑
        partner_map = {p.name: p for p in partners}

        specs = [
            # (이름, 코드, 협력사명, 단가, 리드타임)
            ("프론트 브라켓 A", "OUT-BRK-001", "(주)한국브라켓", 1200, 3),
            ("리어 브라켓 B", "OUT-BRK-002", "(주)한국브라켓", 1500, 3),
            ("메인 하우징", "OUT-HSG-001", "대한하우징(주)", 2500, 5),
            ("서브 하우징", "OUT-HSG-002", "대한하우징(주)", 1800, 4),
            ("엔드캡 A", "OUT-CAP-001", "삼성캡(주)", 750, 2),
            ("엔드캡 B", "OUT-CAP-002", "삼성캡(주)", 800, 2),
            # 테스트용: 삼성캡에서 조달하는 브라켓
            ("사이드 브라켓 C", "OUT-BRK-003", "삼성캡(주)", 900, 2),
        ]

        for name, code, partner_name, price, leadtime in specs:
            partner = partner_map.get(partner_name)
            existing = Product.search([("default_code", "=", code)], limit=1)

            vals = {
                "name": name,
                "default_code": code,
                "type": "consu",
                "is_storable": True,  # Odoo 18: consu + is_storable = 저장가능 제품
                "is_outsourced": True,
                "outsource_partner_id": partner.id if partner else False,
                "outsource_leadtime": leadtime,
                "standard_price": price,
                "list_price": price * 1.2,
            }

            if existing:
                existing.write(vals)
                products |= existing
            else:
                products |= Product.create(vals)

            # 공급업체 가격 정보
            if partner:
                self._create_supplierinfo(products[-1], partner, price, leadtime)

        return products

    def _create_supplierinfo(self, product, partner, price, delay):
        """공급업체 가격 정보 생성"""
        Supplierinfo = self.env["product.supplierinfo"]
        existing = Supplierinfo.search([
            ("partner_id", "=", partner.id),
            ("product_tmpl_id", "=", product.product_tmpl_id.id),
        ], limit=1)

        vals = {
            "partner_id": partner.id,
            "product_tmpl_id": product.product_tmpl_id.id,
            "price": price,
            "min_qty": 100,
            "delay": delay,
        }

        if existing:
            existing.write(vals)
        else:
            Supplierinfo.create(vals)

    def _add_outsource_to_boms(self, outsource_products):
        """기존 BOM에 외주 부품 추가"""
        BOM = self.env["mrp.bom"]
        BOMLine = self.env["mrp.bom.line"]
        Product = self.env["product.product"]

        # 외주 부품 매핑
        out_map = {p.default_code: p for p in outsource_products}

        # BOM별 외주 부품 추가 스펙
        # 완제품 BOM에 외주 부품 추가 (수요 데이터가 완제품 기준)
        # (완제품 코드 패턴, [(외주부품코드, 수량), ...])
        bom_outsource_specs = [
            # 프론트 범퍼 스노우화이트 (86500-BS000SWP) → 삼성캡 브라켓 + 캡 (테스트용)
            ("86500-BS000SWP", [("OUT-BRK-003", 2), ("OUT-CAP-001", 2)]),
            # 프론트 범퍼 에보니블랙 (86500-BS000EBB) → 한국브라켓 + 캡
            ("86500-BS000EBB", [("OUT-BRK-001", 2), ("OUT-CAP-001", 4)]),
            # 리어 범퍼 (86600-BS000*) → 브라켓 + 하우징 + 캡
            ("86600-BS000", [("OUT-BRK-002", 2), ("OUT-HSG-001", 1), ("OUT-CAP-002", 2)]),
            # 도어트림 (82310-BS000*) → 하우징
            ("82310-BS000", [("OUT-HSG-002", 2)]),
            # 그릴 (86500-BS020*) → 캡
            ("86500-BS020", [("OUT-CAP-001", 2)]),
        ]

        added_count = 0

        for code_pattern, outsource_lines in bom_outsource_specs:
            # 해당 패턴의 완제품 찾기
            products = Product.search([
                ("default_code", "=like", f"{code_pattern}%"),
            ])

            for product in products:
                # BOM 찾기
                bom = BOM.search([
                    "|",
                    ("product_id", "=", product.id),
                    ("product_tmpl_id", "=", product.product_tmpl_id.id),
                ], limit=1)

                if not bom:
                    continue

                for out_code, qty in outsource_lines:
                    out_product = out_map.get(out_code)
                    if not out_product:
                        continue

                    # 이미 있는지 확인
                    existing_line = BOMLine.search([
                        ("bom_id", "=", bom.id),
                        ("product_id", "=", out_product.id),
                    ], limit=1)

                    if not existing_line:
                        BOMLine.create({
                            "bom_id": bom.id,
                            "product_id": out_product.id,
                            "product_qty": qty,
                        })
                        added_count += 1

        return added_count

    def _update_config(self):
        """계획 설정에서 자동 발주 활성화"""
        Config = self.env["outsource.planning.config"]
        config = Config.search([], limit=1)

        if config:
            config.write({
                "auto_generate_po": True,
                "outsource_buffer_days": 1,
            })
        else:
            Config.create({
                "auto_generate_po": True,
                "outsource_buffer_days": 1,
            })

    def _create_test_product_set(self, partners):
        """테스트용 완제품 + 외주부품 + BOM + 수요 생성 (매번 새로운 품번)"""
        from datetime import date, timedelta
        import time

        Product = self.env["product.product"]
        BOM = self.env["mrp.bom"]
        BOMLine = self.env["mrp.bom.line"]
        Demand = self.env["production.demand"]

        # 유니크 코드 생성 (타임스탬프 기반)
        suffix = str(int(time.time()))[-6:]  # 마지막 6자리
        out_code = f"TEST-OUT-{suffix}"
        assy_code = f"TEST-ASSY-{suffix}"

        # 협력사 매핑
        partner_map = {p.name: p for p in partners}
        samsung_cap = partner_map.get("삼성캡(주)")

        # 1. 테스트용 외주 부품 생성 (항상 새로 생성)
        test_outsource = Product.create({
            "name": f"테스트 외주부품 {suffix}",
            "default_code": out_code,
            "type": "consu",
            "is_storable": True,
            "is_outsourced": True,
            "outsource_partner_id": samsung_cap.id if samsung_cap else False,
            "outsource_leadtime": 3,
            "standard_price": 500,
            "list_price": 600,
        })

        # 공급업체 가격 정보
        if samsung_cap:
            self._create_supplierinfo(test_outsource, samsung_cap, 500, 3)

        # 2. 테스트용 완제품 생성 (항상 새로 생성)
        test_finished = Product.create({
            "name": f"테스트 조립품 {suffix}",
            "default_code": assy_code,
            "type": "consu",
            "is_storable": True,
            "standard_price": 2000,
            "list_price": 2500,
        })

        # 3. BOM 생성 (완제품 → 외주부품)
        test_bom = BOM.create({
            "product_tmpl_id": test_finished.product_tmpl_id.id,
            "product_qty": 1,
            "type": "normal",
        })

        # BOM 라인: 외주부품 2개 소요
        BOMLine.create({
            "bom_id": test_bom.id,
            "product_id": test_outsource.id,
            "product_qty": 2,
        })

        # 4. 수요 데이터 생성 (향후 7일간)
        today = date.today()
        demand_vals = []
        for i in range(7):
            demand_date = today + timedelta(days=i + 1)
            demand_vals.append({
                "product_id": test_finished.id,
                "demand_date": demand_date,
                "quantity": 100,  # 하루 100개 수요
                "demand_type": "daily",
                "source": "manual",
                "state": "draft",
            })
        Demand.create(demand_vals)

        _logger.info(
            "테스트 데이터 생성: 완제품=%s, 외주부품=%s, 협력사=%s",
            assy_code, out_code, samsung_cap.name if samsung_cap else "없음"
        )

        return f"테스트 제품: {assy_code} → 외주부품: {out_code} (삼성캡, 일 100개×7일)"

    def _create_supply_chain_test(self, partners):
        """다단계 공급망 테스트 데이터 생성

        공급 구조:
        1차 소재공업(생산): 원자재 → 중간부품A 생산 (5일)
        2차 삼성캡(조립): 중간부품A + 자체캡 → 최종외주품 조립 (3일)
        → 우리회사 납품

        총 리드타임: 8일
        """
        from datetime import date, timedelta
        import time

        Product = self.env["product.product"]
        BOM = self.env["mrp.bom"]
        BOMLine = self.env["mrp.bom.line"]
        Route = self.env["supply.chain.route"]
        Tier = self.env["supply.chain.tier"]
        Demand = self.env["production.demand"]

        # 유니크 코드
        suffix = str(int(time.time()))[-6:]
        mid_code = f"SCM-MID-{suffix}"   # 1차에서 생산하는 중간부품
        cap_code = f"SCM-CAP-{suffix}"   # 삼성캡 자체 부품
        out_code = f"SCM-OUT-{suffix}"   # 최종 외주품 (2차에서 조립)
        assy_code = f"SCM-ASSY-{suffix}"  # 우리 완제품

        # 협력사 매핑
        partner_map = {p.name: p for p in partners}
        samsung_cap = partner_map.get("삼성캡(주)")

        # 1차 공급업체 (소재공업) 생성
        sojae = self.env["res.partner"].search([("name", "=", "소재공업(주)")], limit=1)
        if not sojae:
            sojae = self.env["res.partner"].create({
                "name": "소재공업(주)",
                "email": "contact@sojae.co.kr",
                "phone": "031-111-2222",
                "is_supplier_portal": True,
                "supplier_portal_token": f"demo_token_sojae_{suffix}",
                "supplier_rank": 1,
            })

        # 1. 중간부품 생성 (1차 소재공업에서 생산)
        mid_product = Product.create({
            "name": f"중간부품A {suffix}",
            "default_code": mid_code,
            "type": "consu",
            "is_storable": True,
            "standard_price": 500,
            "list_price": 600,
        })

        # 2. 삼성캡 자체 부품 생성
        cap_product = Product.create({
            "name": f"삼성캡 자체캡 {suffix}",
            "default_code": cap_code,
            "type": "consu",
            "is_storable": True,
            "standard_price": 300,
            "list_price": 350,
        })

        # 3. 최종 외주품 생성 (2차 삼성캡에서 조립, 우리에게 납품)
        final_outsource = Product.create({
            "name": f"조립외주품 {suffix}",
            "default_code": out_code,
            "type": "consu",
            "is_storable": True,
            "is_outsourced": True,
            "outsource_partner_id": samsung_cap.id if samsung_cap else False,
            "outsource_leadtime": 8,  # 총 리드타임
            "standard_price": 1500,
            "list_price": 1800,
        })

        # 공급업체 가격 정보
        if samsung_cap:
            self._create_supplierinfo(final_outsource, samsung_cap, 1500, 3)

        # 4. 우리 완제품 생성
        test_finished = Product.create({
            "name": f"완제품 {suffix}",
            "default_code": assy_code,
            "type": "consu",
            "is_storable": True,
            "standard_price": 5000,
            "list_price": 6000,
        })

        # 5. BOM 생성 (완제품 → 최종외주품)
        test_bom = BOM.create({
            "product_tmpl_id": test_finished.product_tmpl_id.id,
            "product_qty": 1,
            "type": "normal",
        })
        BOMLine.create({
            "bom_id": test_bom.id,
            "product_id": final_outsource.id,
            "product_qty": 3,
        })

        # 6. 공급 경로 생성
        route = Route.create({
            "name": f"공급망테스트 경로 {suffix}",
            "product_id": final_outsource.id,
        })

        # 7. 공급 단계 생성 (부품 흐름 포함)
        # 1차: 소재공업 - 원자재로 중간부품A 생산 → 삼성캡으로 납품
        Tier.create({
            "route_id": route.id,
            "sequence": 1,
            "supplier_id": sojae.id,
            "leadtime": 5,
            "tier_type": "produce",
            "output_product_id": mid_product.id,
        })

        # 2차: 삼성캡 - 중간부품A + 자체캡 → 최종외주품 조립 → 우리회사 납품
        Tier.create({
            "route_id": route.id,
            "sequence": 2,
            "supplier_id": samsung_cap.id if samsung_cap else sojae.id,
            "leadtime": 3,
            "tier_type": "assemble",
            "input_product_ids": [(6, 0, [mid_product.id])],
            "additional_component_ids": [(6, 0, [cap_product.id])],
            "output_product_id": final_outsource.id,
        })

        # 8. 수요 데이터 생성 (10일 후부터 - 리드타임 고려)
        today = date.today()
        demand_vals = []
        for i in range(5):
            demand_date = today + timedelta(days=10 + i)
            demand_vals.append({
                "product_id": test_finished.id,
                "demand_date": demand_date,
                "quantity": 50,
                "demand_type": "daily",
                "source": "manual",
                "state": "draft",
            })
        Demand.create(demand_vals)

        _logger.info(
            "공급망 테스트 데이터 생성: 경로=%s\n"
            "  1차 소재공업(생산): → %s\n"
            "  2차 삼성캡(조립): %s + %s → %s → 우리회사",
            route.name, mid_code, mid_code, cap_code, out_code
        )

        return (
            f"공급망 테스트: {assy_code}\n"
            f"  1차 소재공업(생산): → {mid_code} (5일)\n"
            f"  2차 삼성캡(조립): {mid_code} + {cap_code} → {out_code} (3일)"
        )
