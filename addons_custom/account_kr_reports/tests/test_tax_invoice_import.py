import base64
import csv
import io
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestTaxInvoiceImport(TransactionCase):
    """홈택스·스마트빌 원본 파일 반입 — 헤더 자동인식·중복차단·금액 일치."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 한국 차트·세액 계산은 이 회귀시험의 필수 조건이다. 로드 실패를 skip하지 않는다.
        cls.env["account.chart.template"].try_loading(
            "kr", company=cls.env.company, install_demo=False)
        cls.vendor = cls.env["res.partner"].create({
            "name": "T-수지텍", "vat": "123-45-67890", "company_type": "company"})
        cls.tax10 = cls.env["account.tax"].search([
            ("type_tax_use", "=", "purchase"), ("amount", "=", 10),
            ("company_id", "=", cls.env.company.id),
            ("amount_type", "=", "percent")], limit=1)
        if not cls.tax10:
            raise AssertionError("한국 차트 매입 10% 세금이 필요합니다")

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

    HEADER = ["작성일자", "승인번호", "사업자등록번호", "상호", "공급가액", "세액", "합계금액", "원본승인번호"]

    def _row(self, approval, supply=1000000, tax=100000, **kw):
        return ["2026-09-01", approval, kw.get("vat", "123-45-67890"),
                kw.get("partner", "T-수지텍"), supply, tax,
                kw.get("total", supply + tax if isinstance(supply, (int, float)) else ""),
                kw.get("origin", "")]

    def _move(self, approval):
        return self.env["account.move"]._kr_find_by_approval_number(approval)

    def test_row_failure_rolls_back_partner_move_and_lines(self):
        bad, good = "20260901-10000001-10000001", "20260901-10000001-10000002"
        data = self._csv(self.HEADER, [
            self._row(bad, partner="N-TAX orphan vendor", vat=""), self._row(good)])
        Move = self.env["account.move"]
        original_create = type(Move).create
        failed_ids = []

        def fail_after_create(model, vals_list):
            records = original_create(model, vals_list)
            if records.filtered(lambda m: m.kr_approval_number == bad):
                failed_ids.extend(records.ids)
                raise ValidationError("N-TAX injected post-create failure")
            return records

        with patch.object(type(Move), "create", fail_after_create):
            wiz = self._run(data, create_partner=True)
        self.assertIn("오류 1건", wiz.result)
        self.assertFalse(self._move(bad))
        self.assertFalse(self.env["account.move.line"].search([("move_id", "in", failed_ids)]))
        self.assertFalse(self.env["res.partner"].search([("name", "=", "N-TAX orphan vendor")]))
        self.assertEqual(len(self._move(good)), 1, wiz.result)

    def test_sql_failure_does_not_poison_following_rows(self):
        bad, good = "20260901-20000001-20000001", "20260901-20000001-20000002"
        original_create = type(self.env["account.move"]).create

        def fail_sql_after_create(model, vals_list):
            records = original_create(model, vals_list)
            if records.filtered(lambda m: m.kr_approval_number == bad):
                model.env.cr.execute("SELECT 1 / 0")
            return records

        with patch.object(type(self.env["account.move"]), "create", fail_sql_after_create):
            wiz = self._run(self._csv(self.HEADER, [self._row(bad), self._row(good)]))
        self.assertIn("오류 1건", wiz.result)
        self.assertFalse(self._move(bad))
        self.assertEqual(len(self._move(good)), 1, wiz.result)

    def test_malformed_amounts_are_row_errors_not_zero_or_batch_abort(self):
        bad_values = ["1.2.3", "oops", "오류100원", "1,23", "nan", float("inf")]
        rows = [self._row("20260901-30000001-%08d" % i, value, 0,
                          partner="N-TAX malformed vendor", vat="", total="")
                for i, value in enumerate(bad_values, 1)]
        good = "20260901-30000001-99999999"
        rows.append(self._row(good))
        wiz = self._run(self._csv(self.HEADER, rows), create_partner=True)
        self.assertIn("오류 6건", wiz.result)
        self.assertEqual(len(self._move(good)), 1, wiz.result)
        self.assertFalse(self.env["res.partner"].search([("name", "=", "N-TAX malformed vendor")]))

    def test_explicit_zero_total_is_checked(self):
        approval = "20260901-40000001-40000001"
        wiz = self._run(self._csv(self.HEADER, [self._row(approval, total=0)]))
        self.assertIn("오류 1건", wiz.result)
        self.assertFalse(self._move(approval))

    def test_negative_tax_is_preserved_in_purchase_refund(self):
        approval = "20260901-50000001-50000001"
        origin = "20260831abcdefgh12345678"
        wiz = self._run(self._csv(self.HEADER, [
            self._row(approval, -1000000, -100000, origin=origin)]), post_moves=True)
        move = self._move(approval)
        self.assertEqual(move.move_type, "in_refund", wiz.result)
        self.assertEqual(move.state, "posted", wiz.result)
        self.assertEqual((move.amount_untaxed, move.amount_tax, move.amount_total),
                         (1000000, 100000, 1100000))
        self.assertEqual(-move.amount_total, -1100000, "파일의 취소 방향을 포함한 총액")
        self.assertEqual(move.kr_tax_type, "taxable")
        self.assertTrue(move.kr_is_correction)
        self.assertEqual(move.kr_origin_number, "20260831-ABCDEFGH-12345678")
        self.assertEqual(sum(move.line_ids.mapped("balance")), 0)
        self.assertEqual(sum(move.line_ids.filtered("tax_line_id").mapped("balance")), -100000)

    def test_negative_tax_is_preserved_in_sales_refund(self):
        approval = "20260901-50000002-50000002"
        wiz = self._run(self._csv(self.HEADER, [self._row(approval, -1000000, -100000)]),
                        direction="out_invoice", post_moves=True)
        move = self._move(approval)
        self.assertEqual(move.move_type, "out_refund", wiz.result)
        self.assertEqual(move.state, "posted", wiz.result)
        self.assertEqual((move.amount_untaxed, move.amount_tax, move.amount_total),
                         (1000000, 100000, 1100000))
        self.assertEqual(sum(move.line_ids.filtered("tax_line_id").mapped("balance")), 100000)

    def test_kr_price_included_tax_matches_file(self):
        self.assertTrue(self.tax10.price_include, "한국 기본 내부포함 세목을 검증해야 한다")
        approval = "20260901-50000003-50000003"
        Wizard = type(self.env["kr.tax.invoice.import"])
        with patch.object(Wizard, "_pick_tax", return_value=self.tax10):
            wiz = self._run(self._csv(self.HEADER, [self._row(approval)]))
        move = self._move(approval)
        self.assertEqual((move.amount_untaxed, move.amount_tax, move.amount_total),
                         (1000000, 100000, 1100000), wiz.result)

    def test_unrepresentable_tax_rolls_back_instead_of_silent_change(self):
        approval = "20260901-60000001-60000001"
        # 9.5% 파일에 10% 세목이 선택되더라도 금액 대사에서 생성분을 되돌린다.
        wiz = self._run(self._csv(self.HEADER, [self._row(
            approval, 1000000, 95000, partner="N-TAX wrong rate vendor", vat="")]),
            create_partner=True)
        self.assertIn("오류 1건", wiz.result)
        self.assertFalse(self._move(approval))
        self.assertFalse(self.env["res.partner"].search([("name", "=", "N-TAX wrong rate vendor")]))

    def test_opposite_signs_are_rejected(self):
        approval = "20260901-60000002-60000002"
        wiz = self._run(self._csv(self.HEADER, [self._row(approval, 1000000, -100000)]))
        self.assertIn("오류 1건", wiz.result)
        self.assertFalse(self._move(approval))

    def test_failed_post_rolls_back_only_that_post_and_keeps_valid_draft(self):
        bad, good = "20260901-70000001-70000001", "20260901-70000001-70000002"
        Move = type(self.env["account.move"])
        original_post = Move.action_post

        def fail_after_post(records):
            result = original_post(records)
            if records.filtered(lambda m: m.kr_approval_number == bad):
                raise ValidationError("N-TAX injected post failure")
            return result

        with patch.object(Move, "action_post", fail_after_post):
            wiz = self._run(self._csv(self.HEADER, [self._row(bad), self._row(good)]), post_moves=True)
        self.assertEqual(self._move(bad).state, "draft", wiz.result)
        self.assertEqual(self._move(good).state, "posted", wiz.result)
        self.assertIn("게시 1건 / 초안으로 남음 1건", wiz.result)

    def test_duplicate_normalization_and_cancelled_number_stay_reserved(self):
        approval = "20260901-ABCDEFAB-12345678"
        data = self._csv(self.HEADER, [self._row(approval), self._row(approval.replace("-", "").lower())])
        wiz = self._run(data)
        self.assertIn("중복(건너뜀) 1건", wiz.result)
        self._move(approval).button_cancel()
        retry = self._run(data)
        self.assertIn("생성 0건 / 중복(건너뜀) 2건", retry.result)
        self.assertEqual(len(self._move(approval)), 1)

    def test_import_company_tax_partner_scope_and_global_approval_contract(self):
        company = self.env.company
        other = self.env["res.company"].create({"name": "N-TAX other company", "currency_id": company.currency_id.id})
        self.env["account.chart.template"].try_loading("kr", company=other, install_demo=False)
        restricted = self.env["res.partner"].create({"name": "N-TAX other only vendor", "company_id": other.id})
        other_env = self.env(context=dict(self.env.context, allowed_company_ids=[other.id]))
        other_wiz = other_env["kr.tax.invoice.import"].create({
            "file": self._csv(self.HEADER, [self._row("20260901-80000001-80000001")]),
            "filename": "other.csv"})
        other_wiz.action_import()
        other_move = other_env["account.move"]._kr_find_by_approval_number("20260901-80000001-80000001")
        self.assertEqual(other_move.company_id, other, other_wiz.result)
        self.assertEqual(other_move.invoice_line_ids.tax_ids.company_id, other)
        # 1.5.1의 전사 승인번호 중복 정책은 회사가 달라도 유지한다.
        duplicate = self._run(self._csv(self.HEADER, [self._row("202609018000000180000001")]))
        self.assertIn("생성 0건 / 중복(건너뜀) 1건", duplicate.result)
        self.assertNotIn(other.name, duplicate.result)
        scoped_wiz = self.env["kr.tax.invoice.import"].with_context(
            allowed_company_ids=[company.id, other.id]).create({
                "file": self._csv(self.HEADER, [self._row("20260901-80000002-80000002", partner=restricted.name, vat="")]),
                "filename": "scope.csv"})
        scoped_wiz.action_import()
        self.assertIn("거래처 미등록(건너뜀) 1건", scoped_wiz.result)
        self.assertFalse(self._move("20260901-80000002-80000002"))
