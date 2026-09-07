from odoo import api, models, _
from odoo.exceptions import ValidationError

from .account_journal import (
    KR_BANK_DEFAULT_ACCOUNT_TYPES,
    KR_NATIVE_LIQUIDITY_TYPES,
)


class AccountAccount(models.Model):
    _inherit = "account.account"

    @api.constrains("account_type")
    def _check_kr_bank_journal_account_type(self):
        """은행저널이 쓰는 계정은 허용된 계정유형만 갖도록 유지한다."""
        changed_accounts = self.filtered(
            lambda account: account.account_type
            not in KR_BANK_DEFAULT_ACCOUNT_TYPES
        )
        if not changed_accounts:
            return

        journals = self.env["account.journal"].sudo().search([
            ("type", "=", "bank"),
            ("default_account_id", "in", changed_accounts.ids),
        ], limit=1)
        if journals:
            raise ValidationError(_(
                "은행 저널 '%(journal)s'의 계정과목으로 사용 중인 계정은 "
                "'은행 및 현금', '신용카드', '유동자산' 이외의 계정유형으로 "
                "변경할 수 없습니다. 먼저 계좌 설정에서 다른 계정과목을 "
                "지정하세요.",
                journal=journals.display_name,
            ))

    @api.constrains("account_type", "reconcile")
    def _check_kr_liquidity_account_reconcile(self):
        """유동자산 계정을 은행저널에 쓰면 `상계 허용`이 켜져 있어야 한다.

        Odoo 는 잔액계산·상계·역분개 자동상계에서 계정유형이 `은행 및 현금`인지
        **또는** `상계 허용`인지를 봅니다. 유동자산 계정은 앞을 만족하지 못하므로
        뒤가 꺼지면 은행저널 전표의 잔액이 계산되지 않습니다.
        """
        risky = self.filtered(
            lambda account: not account.reconcile
            and account.account_type not in KR_NATIVE_LIQUIDITY_TYPES
        )
        if not risky:
            return

        journals = self.env["account.journal"].sudo().search([
            ("type", "in", ("bank", "cash")),
            ("default_account_id", "in", risky.ids),
        ], limit=1)
        if journals:
            raise ValidationError(_(
                "'%(account)s'은(는) 은행 저널 '%(journal)s'의 계정과목입니다. "
                "'은행 및 현금' 유형이 아닌 계정을 은행 저널에 쓰려면 "
                "'상계 허용'을 켜 두어야 잔액계산과 상계가 정상 동작합니다.",
                account=journals.default_account_id.display_name,
                journal=journals.display_name,
            ))
