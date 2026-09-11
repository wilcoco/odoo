from odoo.tests import TransactionCase, tagged

from odoo.addons.account_kr_reports.tools import report_adjust


@tagged("post_install", "-at_install")
class TestReportAdjust(TransactionCase):
    """표준 보고서·계정 설정 보정(tools/report_adjust.py) — 결함 복원 후 보정·멱등·사용자 수식 보존."""

    def test_missing_optional_report_is_ignored(self):
        """Enterprise 보고서가 없는 Community DB에서도 설치·업그레이드가 실패하지 않는다."""
        expression = report_adjust._balance_expression(
            self.env, "account_kr_reports.nonexistent_optional_report_line"
        )
        self.assertFalse(expression)

    def _kr_expression(self, xmlid):
        expression = report_adjust._balance_expression(self.env, xmlid)
        if not expression:
            self.skipTest("%s 없음 — l10n_kr_reports 미설치 DB" % xmlid)
        return expression

    def test_kr_pl_operating_income_subtracts_expenses(self):
        expression = self._kr_expression("l10n_kr_reports.l10n_kr_pl_income")
        expression.formula = "KR_GRP.balance + KR_EXP.balance"  # 표준 모듈의 결함 수식
        report_adjust.fix_kr_pl_formulas(self.env)
        self.assertEqual(expression.formula, "KR_GRP.balance - KR_EXP.balance")
        self.assertEqual(report_adjust.fix_kr_pl_formulas(self.env), 0, "재실행 멱등")

    def test_kr_pl_tax_expense_includes_corporate_tax_account(self):
        expression = self._kr_expression("l10n_kr_reports.l10n_kr_pl_tax_expense")
        expression.formula = "63"
        report_adjust.fix_kr_pl_formulas(self.env)
        self.assertEqual(expression.formula, "63 + 67")

    def test_kr_pl_user_customized_formula_is_preserved(self):
        expression = self._kr_expression("l10n_kr_reports.l10n_kr_pl_income")
        custom = "KR_REV.balance - KR_COS.balance - KR_EXP.balance"
        expression.formula = custom
        report_adjust.fix_kr_pl_formulas(self.env)
        self.assertEqual(expression.formula, custom, "예상 결함과 다른 수식은 건드리지 않음")

    def test_upgrade_hook_reapplies_fix(self):
        expression = self._kr_expression("l10n_kr_reports.l10n_kr_pl_income")
        expression.formula = "KR_GRP.balance + KR_EXP.balance"  # 표준 모듈 업그레이드로 되돌아간 상황
        self.env["kr.fs.line"]._kr_adjust_standard_reports()
        self.assertEqual(expression.formula, "KR_GRP.balance - KR_EXP.balance")

    def test_non_operating_income_accounts_become_income_other(self):
        Account = self.env["account.account"]
        other = Account.create({"code": "429991", "name": "T-영업외수익", "account_type": "income"})
        sales = Account.create({"code": "419991", "name": "T-매출", "account_type": "income"})
        changed = report_adjust.fix_non_operating_income_types(self.env)
        self.assertIn(other, changed)
        self.assertEqual(other.account_type, "income_other")
        self.assertEqual(sales.account_type, "income", "41 매출 계정은 그대로")
        self.assertFalse(report_adjust.fix_non_operating_income_types(self.env), "재실행 멱등")
