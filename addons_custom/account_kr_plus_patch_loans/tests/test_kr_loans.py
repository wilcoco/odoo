from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestKrLoans(AccountTestInvoicingCommon):
    """차입금 한국식 확장 — 기준정보 전용 승인과 상태 보정."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.misc_journal = cls.company_data["default_journal_misc"]
        cls.account_long = cls.company_data["default_account_payable"]
        cls.account_short = cls.company_data["default_account_payable"]
        cls.account_expense = cls.company_data["default_account_expense"]

    def _make_loan(self, lines, **kwargs):
        """lines: [(일자, 원금, 이자), ...]"""
        values = {
            "name": "테스트 차입금",
            "date": fields.Date.from_string("2024-01-01"),
            "amount_borrowed": sum(line[1] for line in lines),
            "interest": sum(line[2] for line in lines),
            "duration": len(lines),
            "long_term_account_id": self.account_long.id,
            "short_term_account_id": self.account_short.id,
            "expense_account_id": self.account_expense.id,
            "journal_id": self.misc_journal.id,
            "line_ids": [
                Command.create({"date": date, "principal": principal, "interest": interest})
                for date, principal, interest in lines
            ],
        }
        values.update(kwargs)
        return self.env["account.loan"].create(values)

    def test_manage_only_confirm_creates_no_entries(self):
        """기준정보 전용으로 승인하면 전표를 만들지 않고 '실행 중'이 된다."""
        loan = self._make_loan(
            [("2024-06-30", 0, 1000), ("2024-12-31", 1000000, 1000)],
            kr_manage_only=True,
        )
        before = self.env["account.move"].search_count([])
        loan.action_confirm()
        self.assertEqual(loan.state, "running")
        self.assertEqual(self.env["account.move"].search_count([]), before)
        self.assertFalse(loan.line_ids.generated_move_ids)

    def test_manage_only_open_ended_skips_principal_check(self):
        """만기 미정이면 원금 합계가 차입금액과 달라도 승인된다."""
        loan = self._make_loan(
            [("2024-06-30", 0, 1000)],
            amount_borrowed=1000000,
            kr_manage_only=True,
        )
        with self.assertRaises(UserError):
            loan.action_confirm()
        loan.kr_open_ended = True
        loan.action_confirm()
        self.assertEqual(loan.state, "running")

    def test_state_fixed_when_every_line_is_skipped(self):
        """전용 모드가 아니어도 건너뛰기로 생성 전표가 0건이면 상태를 보정한다."""
        loan = self._make_loan(
            [("2024-06-30", 0, 1000), ("2024-12-31", 1000000, 1000)],
            kr_manage_only=False,
            skip_until_date=fields.Date.from_string("2025-12-31"),
        )
        before = self.env["account.move"].search_count([])
        loan.action_confirm()
        self.assertEqual(loan.state, "running")
        self.assertEqual(self.env["account.move"].search_count([]), before)

    def test_standard_flow_still_creates_entries(self):
        """전용 모드가 아니고 미래 회차가 있으면 표준대로 전표를 만든다(회귀 방지)."""
        future = fields.Date.add(fields.Date.context_today(self.env.user), years=1)
        loan = self._make_loan(
            [(fields.Date.to_string(future), 1000000, 1000)],
            kr_manage_only=False,
        )
        loan.action_confirm()
        self.assertEqual(loan.state, "running")
        self.assertTrue(loan.line_ids.generated_move_ids)

    def test_rate_history(self):
        """이자율 이력을 넣으면 현재 이자율이 최신 값으로 맞춰지고 일자별 조회가 된다."""
        loan = self._make_loan([("2024-12-31", 1000000, 1000)], kr_interest_rate=3.99)
        self.env["account.loan.rate"].create(
            [
                {"loan_id": loan.id, "date_from": "2024-01-01", "rate": 3.99},
                {"loan_id": loan.id, "date_from": "2024-11-28", "rate": 4.60, "reason": "만기 연장"},
            ]
        )
        self.assertEqual(loan.kr_interest_rate, 4.60)
        self.assertEqual(loan.kr_rate_on(fields.Date.from_string("2024-06-30")), 3.99)
        self.assertEqual(loan.kr_rate_on(fields.Date.from_string("2024-12-01")), 4.60)

    def test_rollover_is_not_new_money(self):
        """차환(연장) 약정은 신규 조달액으로 잡지 않는다."""
        original = self._make_loan([("2024-12-31", 1000000, 1000)])
        rollover = self._make_loan(
            [("2025-12-31", 1000000, 1000)],
            name="테스트 차입금(연장)",
            date="2024-12-31",
            kr_rollover_from_id=original.id,
        )
        self.assertEqual(original.kr_new_money, original.amount_borrowed)
        self.assertEqual(rollover.kr_new_money, 0)
        self.assertEqual(original.kr_rollover_to_ids, rollover)

    def test_actual_interest_comparison(self):
        """회차에 실제 전표를 연결하면 이자 차이가 계산된다."""
        loan = self._make_loan([("2024-12-31", 1000000, 1000)], kr_manage_only=True)
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.misc_journal.id,
                "date": "2024-12-31",
                "line_ids": [
                    Command.create({"account_id": self.account_expense.id, "debit": 900, "credit": 0}),
                    Command.create({"account_id": self.account_long.id, "debit": 0, "credit": 900}),
                ],
            }
        )
        line = loan.line_ids[0]
        line.kr_actual_move_ids = [Command.set(move.ids)]
        self.assertEqual(line.kr_actual_interest, 900)
        self.assertEqual(line.kr_interest_diff, 100)
