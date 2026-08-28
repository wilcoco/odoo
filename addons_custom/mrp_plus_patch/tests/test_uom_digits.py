from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestUomDigits(TransactionCase):
    """수량 자리수가 소수점을 표시할 수 있는 상태인지 확인."""

    def test_uom_precision_restored(self):
        """'Product Unit of Measure' 정확도가 1자리 이상 — 소수점 표시 가능."""
        digits = self.env["decimal.precision"].precision_get("Product Unit of Measure")
        self.assertGreaterEqual(
            digits, 1,
            "수량 자리수가 0 — BOM 원재료 소요량(kg) 소수점이 다시 잘린다")

    def test_qty_fields_reference_uom_precision(self):
        """핵심 수량 필드들이 이 정확도를 참조한다 (패치가 닿는 경로 확인)."""
        for model_name, fname in (("mrp.bom", "product_qty"),
                                  ("mrp.bom.line", "product_qty"),
                                  ("mrp.production", "product_qty"),
                                  ("account.move.line", "quantity"),
                                  ("stock.move", "product_uom_qty")):
            field = self.env[model_name]._fields[fname]
            self.assertEqual(field._digits, "Product Unit of Measure",
                             "%s.%s" % (model_name, fname))

    def test_uom_rounding_keeps_decimals(self):
        """기준 단위들의 반올림 계수가 1 미만 — 저장값이 정수로 잘리지 않는다."""
        for uom in (self.env.ref("uom.product_uom_unit"),
                    self.env.ref("uom.product_uom_kgm")):
            self.assertLess(uom.rounding, 1,
                            "%s 반올림 계수가 %s — 소수 수량이 저장 단계에서 잘린다"
                            % (uom.name, uom.rounding))
