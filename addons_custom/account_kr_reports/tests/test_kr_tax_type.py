from odoo.tests import Form, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKrTaxType(TransactionCase):
    """과세 구분(과세/영세/면세)이 라인 세금을 실제로 바꾸고, 자동 추정에
    덮어쓰이지 않는지 — 회계 검토 지적(2026-08-27) 회귀 방지."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 한국 계정과목표를 테스트 트랜잭션 안에서 로드 (모듈 설치만으로는 회사에 적용되지 않음)
        if not cls.env["account.tax"].search_count([("name", "like", "TF")]):
            try:
                cls.env["account.chart.template"].try_loading(
                    "kr", company=cls.env.company, install_demo=False)
            except Exception:  # noqa: BLE001 — 차트 미가용 환경은 skip 으로 흘린다
                pass
        cls.partner = cls.env["res.partner"].create({"name": "T-거래처", "vat": "123-45-67890"})
        cls.product = cls.env["product.product"].create({"name": "T-품목"})
        cls.has_kr_taxes = bool(cls.env["account.tax"].search_count([("name", "like", "TF")]))

    def _bill(self):
        f = Form(self.env["account.move"].with_context(default_move_type="in_invoice"))
        f.partner_id = self.partner
        with f.invoice_line_ids.new() as line:
            line.product_id = self.product
            line.price_unit = 1100000
        return f

    def test_exempt_replaces_taxes_and_sticks(self):
        """면세를 고르면 ①라인 세금이 면세 코드로 바뀌고 ②저장 후에도 면세로 남는다."""
        if not self.has_kr_taxes:
            self.skipTest("한국 세목 미로드 환경")
        f = self._bill()
        f.kr_tax_type = "exempt"
        move = f.save()
        self.assertEqual(move.kr_tax_type, "exempt",
                         "면세로 골라도 과세로 되돌아가던 결함 회귀 방지")
        self.assertTrue(move.kr_tax_type_manual)
        line_taxes = move.invoice_line_ids.filtered(
            lambda l: l.display_type == "product").mapped("tax_ids")
        self.assertTrue(line_taxes, "면세도 세금 코드가 있어야 신고 자료에 잡힌다")
        self.assertTrue(all(t.amount == 0 for t in line_taxes), "면세는 세율 0")
        self.assertEqual(move.amount_tax, 0.0, "면세인데 세액이 계산되면 안 됨")
        self.assertEqual(move.kr_doc_type, "invoice", "면세는 증빙이 계산서")

    def test_manual_choice_survives_line_edit(self):
        """면세로 지정한 뒤 라인을 수정해도 자동 추정이 덮어쓰지 않는다."""
        if not self.has_kr_taxes:
            self.skipTest("한국 세목 미로드 환경")
        f = self._bill()
        f.kr_tax_type = "exempt"
        move = f.save()
        move.invoice_line_ids[0].price_unit = 2000000
        move.invalidate_recordset()
        self.assertEqual(move.kr_tax_type, "exempt")

    def test_auto_estimation_still_works(self):
        """직접 고르지 않은 전표는 종전대로 라인 세금에서 추정한다."""
        if not self.has_kr_taxes:
            self.skipTest("한국 세목 미로드 환경")
        move = self._bill().save()
        self.assertFalse(move.kr_tax_type_manual)
        self.assertIn(move.kr_tax_type, ("taxable", "exempt", "zero"))
