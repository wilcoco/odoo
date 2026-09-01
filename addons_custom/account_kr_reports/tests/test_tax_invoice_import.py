import base64
import csv
import io

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTaxInvoiceImport(TransactionCase):
    """홈택스·스마트빌 원본 파일 반입 — 헤더 자동인식·중복차단·금액 일치."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor = cls.env["res.partner"].create({
            "name": "T-수지텍", "vat": "123-45-67890", "company_type": "company"})
        cls.tax10 = cls.env["account.tax"].search([
            ("type_tax_use", "=", "purchase"), ("amount", "=", 10),
            ("amount_type", "=", "percent")], limit=1)

    def _csv(self, header, rows, encoding="cp949"):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
        return base64.b64encode(buf.getvalue().encode(encoding))

    def _run(self, data, filename="src.csv", **kw):
        wiz = self.env["kr.tax.invoice.import"].create(dict(
            {"file": data, "filename": filename, "direction": "in_invoice"}, **kw))
        wiz.action_import()
        return wiz

    def test_header_synonyms_and_amounts(self):
        """스마트빌풍 헤더(발행일자/국세청승인번호/공급가/부가세)도 인식하고
        공급가액·세액이 원본과 일치해야 한다."""
        if not self.tax10:
            self.skipTest("세금 코드 없는 환경(차트 미로드)")
        data = self._csv(
            ["발행일자", "국세청승인번호", "등록번호", "거래처명", "공급가", "부가세", "총액", "적요"],
            [["2026-08-20", "20260820-77777777-88888888", "123-45-67890",
              "T-수지텍", "1000000", "100000", "1100000", "8월분"]])
        wiz = self._run(data)
        mv = self.env["account.move"].search(
            [("kr_approval_number", "=", "20260820-77777777-88888888")])
        self.assertEqual(len(mv), 1, wiz.result)
        self.assertAlmostEqual(mv.amount_untaxed, 1000000.0, places=2,
                               msg="내부포함 세목에서 공급가액이 쪼개지던 결함 회귀 방지")
        self.assertAlmostEqual(mv.amount_tax, 100000.0, places=2)
        self.assertEqual(mv.kr_tax_type, "taxable")
        self.assertFalse(mv.kr_is_correction, "정상 매입분이 수정분으로 오판되면 안 됨")

    def test_duplicate_and_preamble_skipped(self):
        """같은 파일을 두 번 올려도 승인번호 중복은 건너뛴다."""
        if not self.tax10:
            self.skipTest("세금 코드 없는 환경")
        data = self._csv(
            ["작성일자", "승인번호", "사업자등록번호", "상호", "공급가액", "세액", "합계금액"],
            [["20260805", "20260805-11111111-22222222", "123-45-67890",
              "T-수지텍", "1840000", "184000", "2024000"]])
        self._run(data)
        wiz2 = self._run(data)
        self.assertIn("중복", wiz2.result)
        self.assertEqual(self.env["account.move"].search_count(
            [("kr_approval_number", "=", "20260805-11111111-22222222")]), 1)

    def test_unknown_partner_reported_not_created(self):
        """미등록 거래처는 조용히 만들지 않고 목록으로 알려준다."""
        data = self._csv(
            ["작성일자", "승인번호", "사업자등록번호", "상호", "공급가액", "세액"],
            [["2026-08-11", "20260811-99999999-99999999", "220-86-12345",
              "T-미등록사", "100000", "10000"]])
        wiz = self._run(data)
        self.assertIn("미등록 거래처", wiz.result)
        self.assertFalse(self.env["res.partner"].search([("name", "=", "T-미등록사")]))

    def test_missing_headers_raise(self):
        """필수 컬럼이 없으면 무엇이 인식됐는지 알려주며 중단한다."""
        from odoo.exceptions import UserError
        data = self._csv(["이름", "메모"], [["가", "나"]])
        with self.assertRaises(UserError):
            self._run(data)
