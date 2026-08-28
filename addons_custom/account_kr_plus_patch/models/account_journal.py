import re

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
        size=10,
        compute="_compute_kr_sequence_code",
        store=True,
        readonly=False,
        precompute=True,
        tracking=True,
        help=(
            "한국식 전표번호 끝에 붙는 코드입니다. 기존 3자리 형식에서는 "
            "영문 대문자 3자리, 확장 형식에서는 영문 대문자와 숫자 2~10자리를 "
            "사용합니다."
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
            sequence_format = (
                journal.company_id.kr_move_sequence_format or "legacy"
            )
            pattern = (
                r"[A-Z]{3}"
                if sequence_format == "legacy"
                else r"[A-Z0-9]{2,10}"
            )
            if not re.fullmatch(pattern, journal.kr_sequence_code or ""):
                if sequence_format == "legacy":
                    message = _(
                        "기존 3자리 전표번호 형식에서는 전표유형 코드를 "
                        "영문 대문자 3자리로 입력해야 합니다. 예: PUR, SAL, GEN, BNK"
                    )
                else:
                    message = _(
                        "확장 전표번호 형식에서는 전표유형 코드를 "
                        "영문 대문자와 숫자 2~10자리로 입력해야 합니다. "
                        "예: PUR, BANK01"
                    )
                raise ValidationError(message)

    def _kr_get_sequence_code(self):
        self.ensure_one()
        return (
            self.kr_sequence_code
            or JOURNAL_TYPE_SEQUENCE_CODES.get(self.type, "GEN")
        )
