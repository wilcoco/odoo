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
KR_MOVE_SEQUENCE_SHARED_SQL_SUFFIX = r"([A-Z]{3}|-[A-Z0-9]{2,10})?"
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

    kr_move_number_display = fields.Char(
        string="전표번호",
        compute="_compute_kr_move_number_display",
        help="초안은 '전기 시 자동 생성', 전기된 전표는 실제 전표번호를 표시합니다.",
    )
    kr_primary_partner_id = fields.Many2one(
        "res.partner",
        string="거래처",
        compute="_compute_kr_primary_partner_id",
        store=True,
        help="전표 거래처가 없으면 첫 번째 유효 전표 항목의 거래처를 표시합니다.",
    )
    kr_primary_reference = fields.Char(
        string="참조",
        compute="_compute_kr_primary_reference",
        store=True,
        help="참조, 원본 문서, 결제 참조 중 처음 입력된 내용을 표시합니다.",
    )
    kr_bank_journal_ids = fields.Many2many(
        "account.journal",
        "account_move_kr_bank_journal_rel",
        "move_id",
        "journal_id",
        string="보통예금 종류",
        compute="_compute_kr_bank_journal_ids",
        store=True,
        check_company=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        help=(
            "전표의 예금·단기금융상품 라인에 연결된 계좌 설정(은행 저널)을 "
            "표시합니다. 은행계좌 계정과목을 쓰지 않은 전표는 비어 있습니다."
        ),
    )
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

    # ------------------------------------------------------------------
    # 수기 표시(is_manually_modified)
    #
    # 코어는 컨텍스트가 없으면 모든 write를 수기로 표시한다(account_move.write).
    # 그래서 이관 스크립트·가져오기·마법사는 물론, 판매/구매 주문의 청구서 생성,
    # 결제 등록, 전표 역분개 같은 **오두 업무 로직이 만든 전표까지 전부 '수기'** 가
    # 되었다(2022~2024 Q2 이관분 664건).
    #
    # 기준을 하나로 정한다 — **사람이 화면에서 저장한 것만 수기.**
    #   · 화면 저장(web_save)                → 신규·수정 모두 수기 표시
    #   · 업무 로직·RPC·가져오기·마법사·스크립트 → 표시하지 않음(해제 상태 유지)
    #   · 화면의 신규 등록 폼                  → 처음부터 체크된 상태로 보임(default_get)
    #
    # 프로그램이 의도적으로 표시하려면 vals에 직접 넣거나 kr_manual_edit 컨텍스트를
    # 쓴다. 반대로 표시를 막으려면 코어와 동일하게 skip_is_manually_modified 를 쓴다.
    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "is_manually_modified" in fields_list:
            # 화면에서 새로 등록하는 전표는 '수기'가 체크된 상태로 시작한다.
            # 프로그램 create 는 코어가 저장 직후 False 로 초기화하므로 값에 영향이 없고,
            # 화면 저장으로 확정될 때만 아래 create 오버라이드가 True 로 되살린다.
            values["is_manually_modified"] = True
        return values

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        # 코어 create 는 끝에서 항상 False 로 초기화한다(업무 로직 생성분 = 해제).
        # 화면에서 새로 등록한 전표만 되살린다.
        if self.env.context.get("kr_manual_edit"):
            moves.with_context(skip_is_manually_modified=True).write(
                {"is_manually_modified": True}
            )
        return moves

    def write(self, vals):
        if (
            "is_manually_modified" not in vals
            and not self.env.context.get("kr_manual_edit")
            and not self.env.context.get("skip_is_manually_modified")
        ):
            return super(
                AccountMove, self.with_context(skip_is_manually_modified=True)
            ).write(vals)
        return super().write(vals)

    def web_save(self, vals, specification, next_id=None):
        """폼·목록 인라인 저장 = 사람이 직접 등록·수정 → 수기 표시.

        코어 web_save 는 레코드가 있으면 write, 없으면 create 를 호출하므로
        컨텍스트만 실어 보내면 위의 create/write 오버라이드가 각각 처리한다.
        """
        return super(
            AccountMove, self.with_context(kr_manual_edit=True)
        ).web_save(vals, specification, next_id=next_id)

    @api.depends("name", "state")
    def _compute_kr_move_number_display(self):
        for move in self:
            move.kr_move_number_display = (
                move.name
                if move.name and move.name != "/"
                else _("전기 시 자동 생성")
            )

    @api.depends(
        "partner_id",
        "line_ids.partner_id",
        "line_ids.display_type",
        "line_ids.sequence",
    )
    def _compute_kr_primary_partner_id(self):
        for move in self:
            partner = move.partner_id
            if not partner:
                lines = move.line_ids.filtered(
                    lambda line: line.partner_id
                    and line.display_type not in ("line_section", "line_note")
                ).sorted(lambda line: (line.sequence or 0, line._origin.id or 0))
                partner = lines[:1].partner_id
            move.kr_primary_partner_id = partner

    @api.depends("ref", "invoice_origin", "payment_reference")
    def _compute_kr_primary_reference(self):
        for move in self:
            move.kr_primary_reference = next(
                (
                    value
                    for value in (
                        move.ref,
                        move.invoice_origin,
                        move.payment_reference,
                    )
                    if value
                ),
                False,
            )

    @api.depends(
        "line_ids.account_id",
        "line_ids.kr_bank_journal_id",
    )
    def _compute_kr_bank_journal_ids(self):
        for move in self:
            move.kr_bank_journal_ids = move.line_ids.mapped(
                "kr_bank_journal_id"
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
            line = move._kr_get_primary_label_line(require_content=True)
            move.kr_primary_label = line.name if line else False

    def _inverse_kr_primary_label(self):
        for move in self:
            line = (
                move._kr_get_primary_label_line(require_content=True)
                or move._kr_get_primary_label_line()
            )
            if line:
                line.name = move.kr_primary_label

    def _kr_get_primary_label_line(self, require_content=False):
        self.ensure_one()
        if self.move_type in INVOICE_MOVE_TYPES:
            lines = self.invoice_line_ids.filtered(
                lambda line: line.display_type == "product"
            )
        else:
            lines = self.line_ids.filtered(
                lambda line: line.display_type not in ("line_section", "line_note")
            )
        if require_content:
            lines = lines.filtered("name")
        return lines.sorted(
            lambda line: (line.sequence or 0, line._origin.id or 0)
        )[:1]

    def _kr_get_configured_sequence_rule(self):
        self.ensure_one()
        return self.env["account.kr.plus.settings"]._get_global_rule()

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

    @api.model
    def _deduce_sequence_number_reset(self, name):
        """Treat an empty first Korean sequence as a normal new period.

        Odoo asks for the reset period while computing a draft invoice's
        accounting date.  On the first customer or vendor invoice of a day,
        the custom daily domain has no previous name and passes ``False``.
        The core parser rejects that value before our own sequence generator
        can assign the first number.
        """
        if (
            len(self) == 1
            and self._kr_uses_configured_sequence()
            and (not name or name == "/")
        ):
            # The core has no daily reset type.  ``month`` matches the year and
            # month groups used for its lock-date calculation; the actual
            # sequence still resets daily in _get_last_sequence_domain.
            return "month"
        return super()._deduce_sequence_number_reset(name)

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
        if not self.date or not self.company_id:
            return "WHERE FALSE", {}

        refund_prefix = "R" if self.move_type in REFUND_MOVE_TYPES else ""
        where_string = (
            "WHERE company_id = %(company_id)s "
            "AND name != '/' "
            "AND date = %(sequence_date)s "
            "AND name ~ %(sequence_regex)s "
        )
        params = {
            "company_id": self.company_id.id,
            "sequence_date": self.date,
            "sequence_regex": (
                r"^%s[0-9]{14}%s$"
                % (refund_prefix, KR_MOVE_SEQUENCE_SHARED_SQL_SUFFIX)
            ),
        }
        return where_string, params

    def _kr_get_last_shared_sequence_number(self, lock=False):
        """Return the company-wide daily number shared by every TTT code."""
        self.ensure_one()
        move_date = fields.Date.to_date(
            self.date or self.invoice_date or fields.Date.context_today(self)
        )
        refund_prefix = "R" if self.move_type in REFUND_MOVE_TYPES else ""
        if lock:
            lock_name = "account_kr_plus_patch:%s:%s:%s" % (
                self.company_id.id,
                move_date.isoformat(),
                refund_prefix or "N",
            )
            self.env.cr.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                [lock_name],
            )

        self.env["account.move"].flush_model(["name", "company_id"])
        date_part = move_date.strftime("%Y%m%d")
        sequence_regex = (
            r"^%s%s[0-9]{6}%s$"
            % (refund_prefix, date_part, KR_MOVE_SEQUENCE_SHARED_SQL_SUFFIX)
        )
        sequence_extract_regex = r"^%s%s([0-9]{6})" % (
            refund_prefix, date_part
        )
        self.env.cr.execute(
            """
                SELECT COALESCE(
                    MAX(CAST(SUBSTRING(name FROM %s) AS INTEGER)),
                    0
                )
                 FROM account_move
                 WHERE company_id = %s
                   AND date = %s
                   AND id != %s
                   AND name ~ %s
            """,
            [
                sequence_extract_regex,
                self.company_id.id,
                move_date,
                self.id or 0,
                sequence_regex,
            ],
        )
        return self.env.cr.fetchone()[0]

    def _kr_format_shared_sequence(self, sequence_number):
        self.ensure_one()
        move_date = fields.Date.to_date(
            self.date or self.invoice_date or fields.Date.context_today(self)
        )
        refund_prefix = "R" if self.move_type in REFUND_MOVE_TYPES else ""
        sequence = "%s%s%06d" % (
            refund_prefix, move_date.strftime("%Y%m%d"), sequence_number
        )
        if self._kr_get_configured_sequence_rule() == "date_number_type":
            sequence += self.journal_id._kr_get_sequence_code()
        return sequence

    def _get_next_sequence_format(self):
        self.ensure_one()
        if not self._kr_uses_configured_sequence():
            return super()._get_next_sequence_format()
        format_string, format_values = self._get_sequence_format_param(
            self._get_starting_sequence()
        )
        format_values["seq"] = self._kr_get_last_shared_sequence_number()
        return format_string, format_values

    def _set_next_sequence(self):
        self.ensure_one()
        if not self._kr_uses_configured_sequence():
            return super()._set_next_sequence()

        next_number = self._kr_get_last_shared_sequence_number(lock=True) + 1
        if next_number > 999999:
            raise UserError(_(
                "해당 일자의 전표번호 6자리 순번을 모두 사용했습니다."
            ))
        sequence = self._kr_format_shared_sequence(next_number)

        registry = self.env.registry
        triggers = registry._field_triggers[self._fields[self._sequence_field]]
        for inverse_field, triggered_fields in triggers.items():
            for triggered_field in triggered_fields:
                if not triggered_field.store or not triggered_field.compute:
                    continue
                inverse_fields = (
                    registry.field_inverses[inverse_field[0]]
                    if inverse_field else [None]
                )
                for field in inverse_fields:
                    records = self[field.name] if field else self
                    self.env.add_to_compute(triggered_field, records)

        self.env.cr.execute(
            "UPDATE account_move SET name = %s WHERE id = %s",
            [sequence, self.id],
        )
        self.with_context(clear_sequence_mixin_cache=False)[
            self._sequence_field
        ] = sequence
        self._compute_split_sequence()

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

        custom_moves = self.filtered(
            lambda move: move._kr_uses_configured_sequence()
        )
        standard_moves = self - custom_moves
        if standard_moves:
            super(AccountMove, standard_moves)._set_next_made_sequence_gap(
                made_gap
            )

        next_moves = self.env["account.move"]
        named = custom_moves.filtered(lambda move: move.name and move.name != "/")
        for (company, prefix), moves in named.grouped(
            lambda move: (move.company_id, move.sequence_prefix)
        ).items():
            candidates = self.env["account.move"].sudo().search([
                ("company_id", "=", company.id),
                ("sequence_prefix", "=", prefix),
                ("sequence_number", "in", [
                    move.sequence_number + 1 for move in moves
                ]),
            ])
            next_moves |= candidates.filtered(
                lambda move: move._kr_uses_configured_sequence()
            )
        next_moves.made_sequence_gap = made_gap

    @api.depends("journal_id", "sequence_number", "sequence_prefix", "state")
    def _compute_made_sequence_gap(self):
        custom_moves = self.filtered(
            lambda move: move._kr_uses_configured_sequence()
        )
        standard_moves = self - custom_moves
        if standard_moves:
            super(AccountMove, standard_moves)._compute_made_sequence_gap()

        unposted = custom_moves.filtered(
            lambda move: move.sequence_number != 0 and move.state != "posted"
        )
        unposted.made_sequence_gap = True
        posted = custom_moves - unposted
        for (company, prefix), moves in posted.grouped(
            lambda move: (move.company_id, move.sequence_prefix)
        ).items():
            candidates = self.env["account.move"].sudo().search([
                ("company_id", "=", company.id),
                ("sequence_prefix", "=", prefix),
                ("sequence_number", ">=", min(
                    moves.mapped("sequence_number")
                ) - 1),
                ("sequence_number", "<=", max(
                    moves.mapped("sequence_number")
                ) - 1),
            ])
            previous_numbers = set(
                candidates.filtered(
                    lambda move: move._kr_uses_configured_sequence()
                ).mapped("sequence_number")
            )
            for move in moves:
                move.made_sequence_gap = (
                    move.sequence_number > 1
                    and move.sequence_number - 1 not in previous_numbers
                )

    def _inverse_name(self):
        if self.env.context.get("kr_sequence_repair_only_name"):
            return
        return super()._inverse_name()

    def action_post(self):
        mapping = self.env["account.move.line"]._kr_bank_journals_by_account(
            self.company_id
        )
        for move in self:
            ambiguous_lines = move.line_ids.filtered(
                lambda item: not item.kr_bank_journal_id
                and len(mapping.get(
                    (item.company_id.id, item.account_id.id)
                ) or ()) > 1
            )
            if ambiguous_lines:
                accounts = ", ".join(
                    ambiguous_lines.mapped("account_id.display_name")
                )
                raise UserError(_(
                    "동일한 계정과목에 은행계좌가 여러 개 연결되어 있습니다. "
                    "다음 분개 라인의 '연결 은행계좌'를 선택해주세요: %s",
                    accounts,
                ))
        return super().action_post()
