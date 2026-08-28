from odoo.tests import TransactionCase, tagged

from ..models.kr_amount_digits import AMOUNT_FIELDS, AMOUNT_PRECISION, UNIT_PRICE_FIELDS


@tagged("post_install", "-at_install")
class TestKrAmountDigits(TransactionCase):
    """금액 Float 은 소수점 0자리, 수량 Float 은 손대지 않았는지 확인."""

    def test_amount_precision_record(self):
        """소수점 정확도 'KR Amount' 가 0자리로 깔려 있어야 한다."""
        precision = self.env["decimal.precision"].search([("name", "=", AMOUNT_PRECISION)])
        self.assertEqual(len(precision), 1)
        self.assertEqual(precision.digits, 0)

    def test_amount_fields_have_no_decimals(self):
        """표에 적힌 금액 필드는 (16, 0) 으로 표시된다."""
        checked = 0
        for model_name, field_names in AMOUNT_FIELDS.items():
            if model_name not in self.env:
                continue
            for fname in field_names:
                field = self.env[model_name]._fields.get(fname)
                if field is None:
                    continue
                self.assertEqual(
                    field.get_digits(self.env), (16, 0),
                    "%s.%s 의 자리수가 0이 아니다" % (model_name, fname))
                checked += 1
        self.assertTrue(checked, "검사한 금액 필드가 하나도 없다 — 패치가 적용되지 않았다")

    def test_unit_price_fields_follow_product_price(self):
        """단가 필드는 'Product Price' 설정을 따른다."""
        expected = self.env["decimal.precision"].precision_get("Product Price")
        for model_name, field_names in UNIT_PRICE_FIELDS.items():
            if model_name not in self.env:
                continue
            for fname in field_names:
                field = self.env[model_name]._fields.get(fname)
                if field is None:
                    continue
                self.assertEqual(field.get_digits(self.env), (16, expected),
                                 "%s.%s" % (model_name, fname))

    def test_quantity_fields_untouched(self):
        """수량은 건드리지 않는다 — 소수점이 필요한 쪽이라 그대로 둬야 한다."""
        self.assertEqual(
            self.env["account.move.line"]._fields["quantity"]._digits,
            "Product Unit of Measure")
        for model_name, fname in (("account.invoice.report", "quantity"),
                                  ("product.product", "quantity_svl"),
                                  ("sale.report", "product_uom_qty"),
                                  ("purchase.bill.line.match", "line_qty")):
            if model_name not in self.env:
                continue
            field = self.env[model_name]._fields.get(fname)
            if field is None:
                continue
            self.assertIsNone(field._digits, "%s.%s 이 패치에 휩쓸렸다" % (model_name, fname))
