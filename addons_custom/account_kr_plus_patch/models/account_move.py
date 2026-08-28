import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError


# 현재 설정에서 선택할 수 있는 두 한국식 형식
KR_MOVE_SEQUENCE_DATE_NUMBER_REGEX = (
    r"^(?P<prefix1>R?)(?P<year>\d{4})(?P<month>\d{2})"
    r"(?P<prefix2>\d{2})(?P<seq>\d{6})(?P<suffix>)$"
)
KR_MOVE_SEQUENCE_DATE_NUMBER_TYPE_REGEX = (
    r"^(?P<prefix1>R?)(?P<year>\d{4})(?P<month>\d{2})"
    r"(?P<prefix2>\d{2})(?P<seq>\d{6})(?P<suffix>[A-Z]{3})$"
)
# 이전 버전에서 발급된 긴 코드 번호는 설정 선택지에서 제거하되 계속 열람할 수 있게 한다.
KR_MOVE_SEQUENCE_LONG_CODE_COMPAT_REGEX = (
    r"^(?P<prefix1>R?)(?P<year>\d{4})(?P<month>\d{2})"
    r"(?P<prefix2>\d{2})(?P<seq>\d{6})(?P<suffix>-[A-Z0-9]{2,10})$"
)
KR_MOVE_SEQUENCE_REGEXES = {
    "date_number": KR_MOVE_SEQUENCE_DATE_NUMBER_REGEX,
    "date_number_type": KR_MOVE_SEQUENCE_DATE_NUMBER_TYPE_REGEX,
    "long_code_compat": KR_MOVE_SEQUENCE_LONG_CODE_COMPAT_REGEX,
}
KR_MOVE_SEQUENCE_SQL_REGEXES = {
    "date_number": r"^R?[0-9]{14}$",
    "date_number_type": r"^R?[0-9]{14}[A-Z]{3}$",
    "long_code_compat": r"^R?[0-9]{14}-[A-Z0-9]{2,10}$",
}
REFUND_MOVE_TYPES = ("out_refund", "in_refund")
INVOICE_MOVE_TYPES = (
    "out_invoice",
    "in_invoice",
    "out_refund",
    "in_refund",
    "out_receipt",
    "in_receipt",
)
KR_MOVE_TYPE_NAMES = {
    "entry": "전표",
    "out_invoice": "매출처 세금계산서",
    "out_refund": "매출처 취소 세금계산서",
    "in_invoice": "매입처 세금계산서",
    "in_refund": "매입처 취소 세금계산서",
    "out_receipt": "매출 영수증",
    "in_receipt": "매입 영수증",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    kr_product_names = fields.Char(
        string="품목명",
        compute="_compute_kr_product_names",
        store=True,
    )
    kr_primary_label = fields.Char(
        string="적요",
        compute="_compute_kr_primary_label",
        inverse="_inverse_kr_primary_label",
    )
    kr_move_type_display = fields.Char(
        string="전표유형",
        compute="_compute_kr_move_type_display",
        store=True,
    )
    kr_approval_status_display = fields.Char(
        string="결재상태",
        compute="_compute_kr_approval_status_display",
    )

    @api.depends(
        "invoice_line_ids.product_id",
        "invoice_line_ids.product_id.name",
        "invoice_line_ids.name",
        "invoice_line_ids.display_type",
    )
    def _compute_kr_product_names(self):
        for move in self:
            labels = []
            lines = move.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            )
            for line in lines:
                label = line.product_id.display_name or line.name
                if label and label not in labels:
                    labels.append(label)
            move.kr_product_names = ", ".join(labels)

    @api.depends("move_type")
    def _compute_kr_move_type_display(self):
        for move in self:
            move.kr_move_type_display = KR_MOVE_TYPE_NAMES.get(
                move.move_type, move.move_type or ""
            )

    @api.depends("pumui_id", "pumui_approval_state")
    def _compute_kr_approval_status_display(self):
        selection = dict(
            self._fields["pumui_approval_state"]._description_selection(self.env)
        )
        for move in self:
            move.kr_approval_status_display = (
                selection.get(move.pumui_approval_state, move.pumui_approval_state)
                if move.pumui_id
                else _("미연결")
            )

    @api.depends(
        "move_type",
        "invoice_line_ids.name",
        "invoice_line_ids.display_type",
        "line_ids.name",
        "line_ids.display_type",
        "line_ids.sequence",
    )
    def _compute_kr_primary_label(self):
        for move in self:
            line = move._kr_get_primary_label_line()
            move.kr_primary_label = line.name if line else False

    def _inverse_kr_primary_label(self):
        for move in self:
            line = move._kr_get_primary_label_line()
            if line:
                line.name = move.kr_primary_label

    def _kr_get_primary_label_line(self):
        self.ensure_one()
        if self.move_type in INVOICE_MOVE_TYPES:
            lines = self.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            )
        else:
            lines = self.line_ids.filtered(
                lambda line: line.display_type not in ("line_section", "line_note")
            )
        return lines.sorted(
            lambda line: (line.sequence or 0, line._origin.id or 0)
        )[:1]

    def _kr_get_configured_sequence_rule(self):
        self.ensure_one()
        return self.company_id.kr_move_sequence_rule or "odoo"

    def _kr_get_configured_sequence_regex(self):
        self.ensure_one()
        return KR_MOVE_SEQUENCE_REGEXES.get(
            self._kr_get_configured_sequence_rule()
        )

    def _kr_get_sequence_rule_for_record(self):
        """과거 전표는 발급 당시 형식, 신규 전표는 현재 회사 설정을 반환한다."""
        self.ensure_one()
        if self.name and self.name != "/":
            for sequence_rule, regex in KR_MOVE_SEQUENCE_REGEXES.items():
                if re.fullmatch(regex, self.name):
                    return sequence_rule
        return self._kr_get_configured_sequence_rule()

    def _kr_get_supported_sequence_regex(self):
        """신규 전표에는 현재 설정을, 기존 전표에는 발급 당시 형식을 사용한다."""
        self.ensure_one()
        if not self.name or self.name == "/":
            return self._kr_get_configured_sequence_regex()
        regex = KR_MOVE_SEQUENCE_REGEXES.get(
            self._kr_get_sequence_rule_for_record()
        )
        return regex if regex and re.fullmatch(regex, self.name) else False

    def _kr_uses_configured_sequence(self):
        """신규 전표와 지원하는 한국식 번호인 전표에만 새 파서를 적용한다.

        설치 전에 전기된 전표는 기존 Odoo 번호와 파서를 그대로 사용하므로
        과거 전표를 재번호화하거나 열람 불가 상태로 만들지 않는다.
        """
        self.ensure_one()
        return bool(self._kr_get_supported_sequence_regex())

    @property
    def _sequence_monthly_regex(self):
        if self and len(self) == 1 and self._kr_uses_configured_sequence():
            return self._kr_get_supported_sequence_regex()
        return super()._sequence_monthly_regex

    @property
    def _sequence_yearly_regex(self):
        if self and len(self) == 1 and self._kr_uses_configured_sequence():
            return self._kr_get_supported_sequence_regex()
        return super()._sequence_yearly_regex

    @property
    def _sequence_year_range_regex(self):
        if self and len(self) == 1 and self._kr_uses_configured_sequence():
            return self._kr_get_supported_sequence_regex()
        return super()._sequence_year_range_regex

    @property
    def _sequence_fixed_regex(self):
        if self and len(self) == 1 and self._kr_uses_configured_sequence():
            return self._kr_get_supported_sequence_regex()
        return super()._sequence_fixed_regex

    @property
    def _sequence_year_range_monthly_regex(self):
        if self and len(self) == 1 and self._kr_uses_configured_sequence():
            return self._kr_get_supported_sequence_regex()
        return super()._sequence_year_range_monthly_regex

    def _compute_split_sequence(self):
        """번호가 아직 배정되지 않은 전표는 코어 파서로 처리한다.

        KR 정규식은 완성된 번호(YYYYMMDD + 6자리 순번 + 유형코드)만 매칭한다.
        초안 전표의 이름은 "/" 이므로 그대로 코어 _compute_split_sequence 에
        넘기면 정규식 매칭이 None 이 되어 AttributeError 로 전기가 실패한다.

        KR 정규식 자체는 채번 시 직전 번호를 파싱하는 데 필요하므로
        (_get_last_sequence_domain·_deduce_sequence_number_reset) 게이트는 끄지
        않고, 이 계산에서만 우회한다. 값은 코어가 "/" 에 대해 내는 결과와 같다.
        """
        pending = self.filtered(lambda move: not move.name or move.name == "/")
        for move in pending:
            move.sequence_prefix = ""
            move.sequence_number = 0
        remaining = self - pending
        if remaining:
            super(AccountMove, remaining)._compute_split_sequence()

    def _get_last_sequence_domain(self, relaxed=False):
        self.ensure_one()
        if not self._kr_uses_configured_sequence():
            return super()._get_last_sequence_domain(relaxed=relaxed)
        if not self.date or not self.journal_id:
            return "WHERE FALSE", {}

        sequence_rule = self._kr_get_sequence_rule_for_record()
        match = re.fullmatch(
            KR_MOVE_SEQUENCE_REGEXES[sequence_rule], self.name or ""
        )
        where_string = (
            "WHERE journal_id = %(journal_id)s "
            "AND name != '/' "
            "AND date = %(sequence_date)s "
            "AND name ~ %(sequence_regex)s "
        )
        params = {
            "journal_id": self.journal_id.id,
            "sequence_date": self.date,
            "sequence_regex": KR_MOVE_SEQUENCE_SQL_REGEXES[sequence_rule],
        }
        if sequence_rule != "date_number":
            sequence_suffix = (
                match.group("suffix")
                if match
                else self.journal_id._kr_get_sequence_code()
            )
            where_string += (
                "AND RIGHT(name, LENGTH(%(sequence_suffix)s)) = "
                "%(sequence_suffix)s "
            )
            params["sequence_suffix"] = sequence_suffix
        if self.move_type in REFUND_MOVE_TYPES:
            where_string += "AND move_type IN ('out_refund', 'in_refund') "
        else:
            where_string += "AND move_type NOT IN ('out_refund', 'in_refund') "
        return where_string, params

    def _get_starting_sequence(self):
        self.ensure_one()
        if not self._kr_uses_configured_sequence():
            return super()._get_starting_sequence()
        move_date = self.date or self.invoice_date or fields.Date.context_today(self)
        refund_prefix = "R" if self.move_type in REFUND_MOVE_TYPES else ""
        starting_sequence = "%s%s000000" % (
            refund_prefix, move_date.strftime("%Y%m%d")
        )
        if self._kr_get_configured_sequence_rule() == "date_number_type":
            starting_sequence += self.journal_id._kr_get_sequence_code()
        return starting_sequence

    def _sequence_matches_date(self):
        self.ensure_one()
        match = False
        for regex in KR_MOVE_SEQUENCE_REGEXES.values():
            match = re.fullmatch(regex, self.name or "")
            if match:
                break
        if not match:
            return super()._sequence_matches_date()
        move_date = fields.Date.to_date(self.date)
        if not move_date:
            return True
        values = match.groupdict()
        return (
            values["year"] == move_date.strftime("%Y")
            and values["month"] == move_date.strftime("%m")
            and values["prefix2"] == move_date.strftime("%d")
            and bool(values["prefix1"])
            == (self.move_type in REFUND_MOVE_TYPES)
        )

    def _set_next_made_sequence_gap(self, made_gap):
        if self.env.context.get("kr_sequence_repair_only_name"):
            return
        return super()._set_next_made_sequence_gap(made_gap)

    def _inverse_name(self):
        if self.env.context.get("kr_sequence_repair_only_name"):
            return
        return super()._inverse_name()

    def action_post(self):
        for move in self:
            ambiguous_lines = self.env["account.move.line"]
            for line in move.line_ids.filtered(
                lambda item: item.account_id.account_type == "asset_cash"
                and not item.kr_bank_journal_id
            ):
                bank_journals = self.env["account.journal"].search([
                    ("type", "=", "bank"),
                    ("company_id", "=", line.company_id.id),
                    ("default_account_id", "=", line.account_id.id),
                ], limit=2)
                if len(bank_journals) > 1:
                    ambiguous_lines |= line
            if ambiguous_lines:
                accounts = ", ".join(
                    ambiguous_lines.mapped("account_id.display_name")
                )
                raise UserError(_(
                    "동일한 당좌예금 계정과목에 은행계좌가 여러 개 연결되어 "
                    "있습니다. 다음 분개 라인의 '연결 은행계좌'를 선택해주세요: %s",
                    accounts,
                ))
        return super().action_post()
