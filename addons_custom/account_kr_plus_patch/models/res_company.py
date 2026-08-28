import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


KR_MOVE_SEQUENCE_RULES = [
    ("date_number", "날짜-번호"),
    ("date_number_type", "날짜-번호-전표유형"),
    ("odoo", "Odoo 기본 (관여하지 않음)"),
]


class ResCompany(models.Model):
    _inherit = "res.company"

    kr_move_sequence_rule = fields.Selection(
        selection=KR_MOVE_SEQUENCE_RULES,
        string="전표번호 형식",
        required=True,
        default="odoo",
        help=(
            "날짜-번호는 YYYYMMDDNNNNNN, 날짜-번호-전표유형은 "
            "YYYYMMDDNNNNNNTTT 형식입니다. Odoo 기본을 선택하면 이 모듈은 "
            "신규 전표번호 발급에 관여하지 않습니다."
        ),
    )

    @api.constrains("kr_move_sequence_rule")
    def _check_kr_move_sequence_rule_codes(self):
        Journal = self.env["account.journal"].sudo().with_context(active_test=False)
        for company in self:
            if company.kr_move_sequence_rule != "date_number_type":
                continue
            journals = Journal.search([("company_id", "=", company.id)])
            invalid = journals.filtered(
                lambda journal: not re.fullmatch(
                    r"[A-Z]{3}", journal.kr_sequence_code or ""
                )
            )
            if invalid:
                raise ValidationError(_(
                    "전표유형 코드를 영문 대문자 3자리로 수정해야 하는 저널이 "
                    "있습니다: %s",
                    ", ".join(invalid.mapped("display_name")),
                ))
