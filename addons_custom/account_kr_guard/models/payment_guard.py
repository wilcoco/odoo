from odoo import models, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    """리포트 #12: 결제대기(미결제 대기) 계정 미설정 → 고아 결제 발생.
    전기 전에 계정 해석 가능 여부를 검사해, 고아 결제를 사전 차단한다."""
    _inherit = "account.payment"

    def _kr_outstanding_account(self):
        """이 결제가 사용할 대기 계정을 해석. 없으면 False."""
        self.ensure_one()
        acc = self.payment_method_line_id.payment_account_id
        if acc:
            return acc
        company = self.company_id or self.env.company
        # 회사 기본 대기계정 (버전별 필드명 방어적 접근)
        fname = ("account_journal_payment_debit_account_id" if self.payment_type == "inbound"
                 else "account_journal_payment_credit_account_id")
        if hasattr(company, fname) and getattr(company, fname):
            return getattr(company, fname)
        return False

    def action_post(self):
        for pay in self:
            if not pay._kr_outstanding_account():
                raise UserError(_(
                    "이 결제수단(%(m)s / %(j)s)에는 결제 대기 계정이 설정되어 있지 않습니다. "
                    "결제를 등록할 수 없습니다. 관리자에게 문의해주세요.\n"
                    "(설정 위치: 회계 > 저널 %(j)s > 결제수단의 '미결제 계정')") % {
                        "m": pay.payment_method_line_id.name or "-",
                        "j": pay.journal_id.name or "-"})
        return super().action_post()
