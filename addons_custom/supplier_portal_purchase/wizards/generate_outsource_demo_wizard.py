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

        # 4. 계획 설정 업데이트 (자동 발주 활성화)
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
        ]

        for name, code, partner_name, price, leadtime in specs:
            partner = partner_map.get(partner_name)
            existing = Product.search([("default_code", "=", code)], limit=1)

            vals = {
                "name": name,
                "default_code": code,
                "type": "product",  # 저장가능 제품 (재고 추적)
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
            # 프론트 범퍼 (86500-BS000*) → 브라켓 + 캡
            ("86500-BS000", [("OUT-BRK-001", 2), ("OUT-CAP-001", 4)]),
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
        Config = self.env["injection.planning.config"]
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
