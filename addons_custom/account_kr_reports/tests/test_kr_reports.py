import base64

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKrReports(TransactionCase):
    """rollback 검증 배터리 승격본 — 대출 멱등·K-재무제표 대차평형·잠금 이력·
    매출 승인번호 매칭·청구↔원장 대사."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "KR테스트거래처", "vat": "123-45-67890"})

    def test_loan_schedule_idempotent(self):
        loan = self.env["kr.loan"].create({
            "name": "T-대출", "partner_id": self.partner.id, "principal": 120_000_000,
            "interest_rate": 5.0, "date_start": "2026-01-15", "maturity_date": "2027-01-15",
            "payment_mode": "monthly"})
        loan.action_generate_schedule()
        self.assertEqual(len(loan.schedule_ids), 12)
        self.assertAlmostEqual(loan.total_interest, 6_000_000, delta=1)
        loan.schedule_ids.sorted("date_due")[0].action_mark_paid()
        loan.action_generate_schedule()  # 재생성 멱등
        self.assertEqual(len(loan.schedule_ids), 12, "지급완료 회차 보존 + 중복 생성 없음")
        dates = loan.schedule_ids.mapped("date_due")
        self.assertEqual(len(dates), len(set(dates)), "회차 날짜 중복 없음")
        mid = loan.schedule_ids.sorted("date_due")[5]
        mid.write({"amount_principal": 20_000_000})
        mid.action_mark_paid()
        loan.action_generate_schedule()
        last = loan.schedule_ids.sorted("date_due")[-1]
        self.assertAlmostEqual(last.amount_principal, 100_000_000, delta=1, msg="잔여원금 배분")
        with self.assertRaises(UserError):
            loan.action_close()  # 잔액 있는 종료 차단

    def test_financial_statement_balance(self):
        AA = self.env["account.account"]
        journal = self.env["account.journal"].search(
            [("type", "=", "general"), ("company_id", "=", self.env.company.id)], limit=1)
        ar = AA.search([("account_type", "=", "asset_receivable")], limit=1)
        rev = AA.search([("account_type", "=", "income")], limit=1)
        if journal and ar and rev:
            mv = self.env["account.move"].create({
                "move_type": "entry", "journal_id": journal.id, "date": "2026-06-30",
                "line_ids": [
                    (0, 0, {"account_id": ar.id, "partner_id": self.partner.id, "debit": 1000, "credit": 0}),
                    (0, 0, {"account_id": rev.id, "debit": 0, "credit": 1000}),
                ]})
            mv.action_post()
        Line = self.env["kr.fs.line"]
        Line.ensure_seed()
        n_bs = Line.search_count([("report", "=", "bs")])
        Line.ensure_seed()
        self.assertEqual(Line.search_count([("report", "=", "bs")]), n_bs, "시드 멱등")
        fs = self.env["kr.financial.statement"].create({"report": "bs", "date_to": "2026-12-31"})
        fs.action_compute()
        amt = {l.name: l.amount for l in fs.line_ids}
        self.assertAlmostEqual(amt.get("자산총계", 0.0), amt.get("부채와 자본총계", 0.0),
                               delta=0.01, msg="대차평형")

    def test_lock_log_directions(self):
        Log = self.env["kr.lock.log"]
        n0 = Log.search_count([])
        company = self.env.company
        company.write({"fiscalyear_lock_date": "1999-12-31"})
        self.assertEqual(Log.search([], order="id desc", limit=1).direction, "tighten")
        # account_safety_security 가 설치된 DB 는 잠금일자 후퇴·해제를 정책으로
        # 차단한다 — 그 환경에서는 차단 동작 자체를 검증하고 종료한다.
        # (loosen/release 로그 방향은 가드 없는 DB·CI 에서 검증됨)
        safety_guard = self.env["ir.module.module"].sudo().search_count(
            [("name", "=", "account_safety_security"), ("state", "=", "installed")])
        if safety_guard:
            from odoo.exceptions import UserError
            with self.assertRaises(UserError, msg="잠금 후퇴는 안전 가드가 막아야 함"):
                company.write({"fiscalyear_lock_date": "1999-06-30"})
            self.assertEqual(Log.search_count([]), n0 + 1, "차단된 write 는 이력 없음")
            return
        company.write({"fiscalyear_lock_date": "1999-06-30"})
        self.assertEqual(Log.search([], order="id desc", limit=1).direction, "loosen")
        company.write({"fiscalyear_lock_date": False})
        self.assertEqual(Log.search([], order="id desc", limit=1).direction, "release")
        company.write({"fiscalyear_lock_date": False})  # 무변경 write
        self.assertEqual(Log.search_count([]), n0 + 3, "무변경 write 는 이력 없음")

    def test_sales_tax_match_idempotent(self):
        journal = self.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", self.env.company.id)], limit=1)
        if not journal:
            self.skipTest("판매 저널 없음")
        inv = self.env["account.move"].create({
            "move_type": "out_invoice", "partner_id": self.partner.id,
            "invoice_date": "2026-07-01",
            "invoice_line_ids": [(0, 0, {"name": "매칭", "quantity": 1, "price_unit": 333000})]})
        inv.action_post()
        rows = ["approval_number,vat,date,total",
                "T-MATCH-1,%s,%s,%s" % (self.partner.vat, inv.invoice_date,
                                        abs(inv.amount_total_signed)),
                "T-MATCH-2,999-99-99999,2020-01-01,1"]
        data = base64.b64encode(("﻿" + "\r\n".join(rows)).encode()).decode()
        w = self.env["kr.sales.tax.match"].create({"file": data, "filename": "t.csv"})
        w.action_match()
        self.assertEqual(inv.kr_approval_number, "T-MATCH-1")
        self.assertIn("T-MATCH-2", w.result, "후보 없음 리포트")
        w2 = self.env["kr.sales.tax.match"].create({"file": data, "filename": "t.csv"})
        w2.action_match()  # 재실행 — 이미 등록분 건너뜀
        self.assertEqual(self.env["account.move"].search_count(
            [("kr_approval_number", "=", "T-MATCH-1")]), 1, "멱등")

    def test_template_download(self):
        for ttype in ("tax_sale", "tax_purchase", "bank", "tax_sale_match"):
            w = self.env["kr.template.download"].create({"template_type": ttype})
            w.action_generate()
            raw = base64.b64decode(w.file).decode("utf-8-sig")
            self.assertEqual(len(raw.strip().splitlines()), 2, "%s: 헤더+예시" % ttype)
