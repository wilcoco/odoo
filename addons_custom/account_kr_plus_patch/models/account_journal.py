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


class AccountJournal(models.Model):
    _inherit = "account.journal"

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
    def _prepare_liquidity_account_vals(self, company, code, vals):
        account_vals = super()._prepare_liquidity_account_vals(
            company, code, vals
        )
        if (
            self.env.context.get("kr_bank_account_setup")
            and vals.get("type") == "bank"
        ):
            account_name = vals.get("name") or _("당좌예금")
            if _("당좌예금") not in account_name:
                account_name = _("%s 당좌예금", account_name)
            account_vals["name"] = account_name
        return account_vals

    @api.model_create_multi
    def create(self, vals_list):
        is_bank_setup = self.env.context.get("kr_bank_account_setup")
        if is_bank_setup:
            vals_list = [dict(vals, type="bank") for vals in vals_list]
        journals = super().create(vals_list)
        if not is_bank_setup:
            return journals

        journals._kr_ensure_bank_default_account()
        journals._kr_post_bank_setup_guide()
        return journals

    def _kr_ensure_bank_default_account(self):
        for journal in self.filtered(
            lambda item: item.type == "bank" and not item.default_account_id
        ):
            account_id = self.env["account.journal"].with_context(
                kr_bank_account_setup=True
            ).with_company(journal.company_id)._create_default_account(
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
            "은행계좌/저널명, 계좌번호, 은행, 당좌예금 계정과목, "
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
                    _("기본 당좌예금 계정과목은 다음 계정으로 연결했어요:"),
                    journal.default_account_id.display_name,
                    _("다음 필드를 확인해 주세요:"),
                    fields_to_check,
                    _(
                        "당좌예금 계정과목은 '은행 및 현금' 유형을 사용해야 해요. "
                        "실제 은행계좌별 잔액을 나누려면 저널마다 별도 "
                        "계정과목을 사용하는 것을 권장해요."
                    ),
                ),
                subtype_xmlid="mail.mt_note",
            )
