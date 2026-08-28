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
