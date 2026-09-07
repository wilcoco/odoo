import re

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


JOURNAL_TYPE_SEQUENCE_CODES = {
    "sale": "SAL",
    "purchase": "PUR",
    "bank": "BNK",
    "cash": "CSH",
    "credit": "CCD",
    "general": "GEN",
}

# 원화 은행저널이 공유하는 표준 계정과목 이름.
KR_SHARED_BANK_ACCOUNT_NAME = "당좌예금"

# 은행저널의 기본 계정과목으로 허용하는 계정유형.
# Odoo 기본값은 asset_cash·liability_credit_card 뿐이지만, 한국 회계에서
# 단기금융상품(MMT·MMF 등)은 '유동자산'으로 분류해야 하므로 asset_current 를
# 함께 허용한다. 잔액계산·상계·역분개는 계정유형이 아니라 `reconcile` 값으로
# 갈리므로, 유동자산 계정을 쓸 때는 자동으로 `reconcile` 을 켠다.
KR_BANK_DEFAULT_ACCOUNT_TYPES = (
    "asset_cash",
    "liability_credit_card",
    "asset_current",
)

# asset_cash 는 Odoo 가 유동성 계정으로 특별 취급하므로 reconcile 이 필요 없다.
KR_NATIVE_LIQUIDITY_TYPES = ("asset_cash", "liability_credit_card")


def _kr_get_default_account_domain(self):
    """은행저널 기본 계정과목에 유동자산(asset_current)을 추가로 허용한다."""
    return """[
        ('deprecated', '=', False),
        ('account_type', 'in', ('asset_cash', 'liability_credit_card', 'asset_current')
                                   if type == 'bank'
                               else ('liability_credit_card',) if type == 'credit'
                               else ('asset_cash',) if type == 'cash'
                               else ('income', 'income_other') if type == 'sale'
                               else ('expense', 'expense_depreciation', 'expense_direct_cost')
                                   if type == 'purchase'
                               else ('asset_receivable', 'asset_cash', 'asset_current',
                                     'asset_non_current', 'asset_prepayments', 'asset_fixed',
                                     'liability_payable', 'liability_credit_card',
                                     'liability_current', 'liability_non_current',
                                     'equity', 'equity_unaffected', 'income', 'income_other',
                                     'expense', 'expense_depreciation', 'expense_direct_cost',
                                     'off_balance'))
    ]"""


class AccountJournal(models.Model):
    _inherit = "account.journal"

    # 코어는 필드 정의 시점에 도메인 함수를 붙잡으므로 메서드 오버라이드가
    # 통하지 않는다. 도메인만 다시 지정한다.
    default_account_id = fields.Many2one(domain=_kr_get_default_account_domain)

    kr_sequence_code = fields.Char(
        string="전표유형 코드",
        # Keep the database column width upgrade-safe; the constraint below
        # enforces the user-facing three-character rule.
        size=10,
        compute="_compute_kr_sequence_code",
        store=True,
        readonly=False,
        precompute=True,
        tracking=True,
        help=(
            "날짜-번호-전표유형 규칙에서 번호 끝에 붙는 영문 대문자 "
            "3자리 코드입니다. 예: PUR, SAL, GEN, BNK"
        ),
    )

    @api.depends("type")
    def _compute_kr_sequence_code(self):
        for journal in self:
            if not journal.kr_sequence_code:
                journal.kr_sequence_code = JOURNAL_TYPE_SEQUENCE_CODES.get(
                    journal.type, "GEN"
                )

    @api.onchange("kr_sequence_code")
    def _onchange_kr_sequence_code(self):
        for journal in self:
            if journal.kr_sequence_code:
                journal.kr_sequence_code = journal.kr_sequence_code.strip().upper()

    @api.constrains("kr_sequence_code", "company_id")
    def _check_kr_sequence_code(self):
        for journal in self:
            if not re.fullmatch(r"[A-Z]{3}", journal.kr_sequence_code or ""):
                raise ValidationError(_(
                    "전표유형 코드는 영문 대문자 3자리로 입력해야 합니다. "
                    "예: PUR, SAL, GEN, BNK"
                ))

    def _kr_get_sequence_code(self):
        self.ensure_one()
        return (
            self.kr_sequence_code
            or JOURNAL_TYPE_SEQUENCE_CODES.get(self.type, "GEN")
        )

    @api.model
    def _kr_find_shared_bank_account(self, company):
        """Return the company-wide 당좌예금 account, if it already exists."""
        Account = self.env["account.account"]
        return Account.sudo().with_company(company).search([
            *Account._check_company_domain(company),
            ("account_type", "=", "asset_cash"),
            ("name", "=", KR_SHARED_BANK_ACCOUNT_NAME),
            ("currency_id", "=", False),
        ], limit=1)

    @api.model
    def _kr_get_shared_bank_account(self, company):
        """Reuse one 당좌예금 account for every won-denominated bank journal.

        실제 은행계좌 구분은 계정과목이 아니라 전표 라인의 `연결 은행계좌`
        (`kr_bank_journal_id`)로 합니다.
        """
        account = self._kr_find_shared_bank_account(company)
        if account:
            return account
        account_id = self.with_company(company)._create_default_account(
            company,
            "bank",
            {"name": KR_SHARED_BANK_ACCOUNT_NAME, "type": "bank"},
        )
        return self.env["account.account"].browse(account_id)

    @api.model
    def _kr_resolve_company(self, vals):
        if vals.get("company_id"):
            return self.env["res.company"].browse(vals["company_id"])
        return self.env.company

    @api.model
    def _fill_missing_values(self, vals, protected_codes=False):
        """계좌 설정에서 만든 원화 은행저널은 공용 당좌예금 계정을 함께 씁니다."""
        if (
            self.env.context.get("kr_bank_account_setup")
            and vals.get("type") == "bank"
            and not vals.get("default_account_id")
            and not vals.get("currency_id")
        ):
            company = self._kr_resolve_company(vals)
            vals["default_account_id"] = self._kr_get_shared_bank_account(
                company
            ).id
        return super()._fill_missing_values(
            vals, protected_codes=protected_codes
        )

    @api.model_create_multi
    def create(self, vals_list):
        is_bank_setup = self.env.context.get("kr_bank_account_setup")
        if is_bank_setup:
            vals_list = [dict(vals, type="bank") for vals in vals_list]
        journals = super().create(vals_list)
        if is_bank_setup:
            journals._kr_ensure_bank_default_account()
        journals._kr_ensure_liquidity_account_reconcilable()
        if is_bank_setup:
            journals._kr_post_bank_setup_guide()
        return journals

    def write(self, vals):
        res = super().write(vals)
        if "default_account_id" in vals or "type" in vals:
            self._kr_ensure_liquidity_account_reconcilable()
        return res

    def _kr_ensure_liquidity_account_reconcilable(self):
        """유동자산 계정을 은행저널에 쓰면 `상계 허용`을 켠다.

        Odoo 는 잔액계산(`_compute_amount_residual`), 상계(`reconcile`),
        역분개 자동상계, 지급수단 계정 검증에서 `계정유형이 은행 및 현금인가`
        **또는** `상계 허용인가`를 봅니다. 유동자산 계정은 앞의 조건을 만족하지
        못하므로 뒤의 조건을 켜 두어야 은행저널이 정상 동작합니다.
        """
        for journal in self.filtered(lambda item: item.type in ("bank", "cash")):
            account = journal.default_account_id
            if (
                account
                and account.account_type not in KR_NATIVE_LIQUIDITY_TYPES
                and not account.reconcile
            ):
                account.sudo().reconcile = True

    def _kr_ensure_bank_default_account(self):
        for journal in self.filtered(
            lambda item: item.type == "bank" and not item.default_account_id
        ):
            if not journal.currency_id:
                journal.default_account_id = self._kr_get_shared_bank_account(
                    journal.company_id
                )
                continue
            # 외화 저널은 계정에 통화가 고정되므로 저널별 계정을 만든다.
            account_id = self.env["account.journal"].with_company(
                journal.company_id
            )._create_default_account(
                journal.company_id,
                "bank",
                {
                    "name": journal.name,
                    "type": "bank",
                    "currency_id": journal.currency_id.id,
                },
            )
            journal.default_account_id = account_id

    def _kr_post_bank_setup_guide(self):
        fields_to_check = _(
            "은행계좌/저널명, 계좌번호, 은행, 계정과목, "
            "저널 코드, 전표유형 코드, 회사"
        )
        for journal in self.filtered(lambda item: item.type == "bank"):
            journal.message_post(
                body=Markup(
                    "<p>%s</p>"
                    "<ul>"
                    "<li>%s <strong>%s</strong></li>"
                    "<li>%s <strong>%s</strong></li>"
                    "<li>%s</li>"
                    "</ul>"
                ) % (
                    _("계좌 설정을 만들었어요."),
                    _("기본 계정과목은 다음 계정으로 연결했어요:"),
                    journal.default_account_id.display_name,
                    _("다음 필드를 확인해 주세요:"),
                    fields_to_check,
                    _(
                        "원화 예금계좌는 회사에 하나뿐인 '당좌예금' 계정과목을 "
                        "함께 쓰고, 실제 은행계좌 구분은 전표 라인의 "
                        "'연결 은행계좌'로 합니다. MMT·MMF 같은 단기금융상품은 "
                        "'유동자산' 유형 계정과목을 골라도 되며, 이때 "
                        "'상계 허용'은 자동으로 켜집니다. 외화 계좌는 통화가 "
                        "고정되므로 계좌별 계정과목을 따로 만듭니다."
                    ),
                ),
                subtype_xmlid="mail.mt_note",
            )
