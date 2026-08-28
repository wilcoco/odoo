import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


KR_MOVE_SEQUENCE_FORMATS = [
    ("legacy", "기존 3자리 형식 (YYYYMMDDNNNNNNTTT)"),
    ("extended", "확장 형식 (YYYYMMDDNNNNNN-TYPECODE)"),
]


class ResCompany(models.Model):
    _inherit = "res.company"

    kr_use_custom_move_sequence = fields.Boolean(
        string="한국식 전표번호 규칙 사용",
        default=False,
        help=(
            "선택하지 않으면 Odoo 저널의 기본 전표번호 규칙을 사용합니다. "
            "기존에 발급된 한국식 전표번호는 이 설정과 관계없이 계속 인식합니다."
        ),
    )
    kr_move_sequence_format = fields.Selection(
        selection=KR_MOVE_SEQUENCE_FORMATS,
        string="한국식 전표번호 형식",
        required=True,
        default="legacy",
        help=(
            "기존 형식은 영문 3자리 유형 코드를 사용합니다. 확장 형식은 "
            "구분자 뒤에 영문 대문자와 숫자 2~10자리 유형 코드를 사용합니다."
        ),
    )

    @api.constrains("kr_use_custom_move_sequence", "kr_move_sequence_format")
    def _check_kr_move_sequence_format_codes(self):
        Journal = self.env["account.journal"].sudo().with_context(active_test=False)
        for company in self:
            if not company.kr_use_custom_move_sequence:
                continue
            journals = Journal.search([("company_id", "=", company.id)])
            if company.kr_move_sequence_format == "legacy":
                invalid = journals.filtered(
                    lambda journal: not re.fullmatch(
                        r"[A-Z]{3}", journal.kr_sequence_code or ""
                    )
                )
            else:
                invalid = journals.filtered(
                    lambda journal: not re.fullmatch(
                        r"[A-Z0-9]{2,10}", journal.kr_sequence_code or ""
                    )
                )
            if invalid:
                raise ValidationError(_(
                    "선택한 전표번호 형식에 맞지 않는 전표유형 코드가 있습니다: %s",
                    ", ".join(invalid.mapped("display_name")),
                ))
