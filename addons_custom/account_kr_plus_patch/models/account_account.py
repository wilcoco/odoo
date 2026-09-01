from odoo import api, models, _
from odoo.exceptions import ValidationError


class AccountAccount(models.Model):
    _inherit = "account.account"

    @api.constrains("account_type")
    def _check_kr_bank_journal_account_type(self):
        """Keep an account used by a bank journal as Bank and Cash."""
        changed_accounts = self.filtered(
            lambda account: account.account_type != "asset_cash"
        )
        if not changed_accounts:
            return

        journals = self.env["account.journal"].sudo().search([
            ("type", "=", "bank"),
            ("default_account_id", "in", changed_accounts.ids),
        ], limit=1)
        if journals:
            raise ValidationError(_(
                "은행 저널 '%(journal)s'의 당좌예금 계정과목으로 사용 중인 "
                "계정은 계정유형을 '은행 및 현금'이 아닌 유형으로 변경할 수 "
                "없습니다. 먼저 계좌 설정에서 다른 당좌예금 계정과목을 "
                "지정하세요.",
                journal=journals.display_name,
            ))
