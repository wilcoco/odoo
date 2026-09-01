import re
from collections import defaultdict
from datetime import date

from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

from .account_move import KR_MOVE_SEQUENCE_REGEXES, REFUND_MOVE_TYPES
from .res_company import KR_MOVE_SEQUENCE_RULES


class AccountKrMoveSequenceRepairWizard(models.TransientModel):
    _name = "account.kr.move.sequence.repair.wizard"
    _description = "전표번호 소급 변경 적용"

    @api.model
    def _default_journal_ids(self):
        company_id = (
            self.env.context.get("default_company_id") or self.env.company.id
        )
        if company_id not in self.env.companies.ids:
            return self.env["account.journal"]
        return self.env["account.journal"].with_context(
            active_test=False
        ).search([
            ("company_id", "=", company_id),
        ])

    state = fields.Selection(
        selection=[
            ("criteria", "조회 조건"),
            ("preview", "변경안 미리보기"),
            ("done", "처리 결과"),
        ],
        default="criteria",
        required=True,
    )
    company_id = fields.Many2one(
        comodel_name="res.company",
        string="회사",
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    current_rule = fields.Selection(
        selection=KR_MOVE_SEQUENCE_RULES,
        compute="_compute_current_rule",
        string="현재 전표번호 형식",
        readonly=True,
    )
    preview_rule = fields.Selection(
        selection=KR_MOVE_SEQUENCE_RULES,
        string="미리보기 기준 형식",
        readonly=True,
    )
    date_from = fields.Date(
        string="시작일",
        required=True,
        default=lambda self: date(fields.Date.context_today(self).year, 1, 1),
    )
    date_to = fields.Date(
        string="종료일",
        required=True,
        default=fields.Date.context_today,
    )
    journal_ids = fields.Many2many(
        comodel_name="account.journal",
        string="대상 저널",
        required=True,
        default=lambda self: self._default_journal_ids(),
        domain="[('company_id', '=', company_id)]",
        help=(
            "선택한 회사의 활성·보관 저널이 모두 기본 선택됩니다. "
            "필요하면 여러 저널을 남겨 범위를 줄일 수 있습니다."
        ),
    )
    include_draft = fields.Boolean(
        string="직접 지정 전표도 포함",
        help=(
            "전기 전표는 항상 검사합니다. 선택하면 아직 전기되지 않았지만 "
            "'/' 대신 전표번호를 직접 지정한 초안 전표도 검사합니다."
        ),
    )
    line_ids = fields.One2many(
        comodel_name="account.kr.move.sequence.repair.line",
        inverse_name="wizard_id",
        string="점검 결과",
        readonly=True,
    )
    target_count = fields.Integer(compute="_compute_counts", string="대상")
    ready_count = fields.Integer(compute="_compute_counts", string="적용 가능")
    blocked_count = fields.Integer(compute="_compute_counts", string="적용 불가")
    applied_count = fields.Integer(compute="_compute_counts", string="적용 완료")
    result_message = fields.Text(string="처리 결과", readonly=True)

    def _compute_current_rule(self):
        rule = self.env["account.kr.plus.settings"]._get_global_rule()
        for wizard in self:
            wizard.current_rule = rule

    @api.depends("line_ids.result_state")
    def _compute_counts(self):
        for wizard in self:
            wizard.target_count = len(wizard.line_ids)
            wizard.ready_count = len(
                wizard.line_ids.filtered(lambda line: line.result_state == "ready")
            )
            wizard.blocked_count = len(
                wizard.line_ids.filtered(lambda line: line.result_state == "blocked")
            )
            wizard.applied_count = len(
                wizard.line_ids.filtered(lambda line: line.result_state == "applied")
            )

    @api.onchange("company_id")
    def _onchange_company_id(self):
        for wizard in self:
            wizard.journal_ids = self.env["account.journal"].with_context(
                active_test=False
            ).search([
                ("company_id", "=", wizard.company_id.id),
            ])

    def _check_account_manager(self):
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError(_("회계 관리자만 전표번호를 점검하거나 수정할 수 있습니다."))
        if self.company_id.id not in self.env.companies.ids:
            raise AccessError(_("접근할 수 없는 회사의 전표번호는 수정할 수 없습니다."))

    def _get_move_domain(self, include_all_states=False, ignore_journals=False):
        self.ensure_one()
        domain = [
            ("company_id", "=", self.company_id.id),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ]
        if self.journal_ids and not ignore_journals:
            domain.append(("journal_id", "in", self.journal_ids.ids))
        if not include_all_states:
            if self.include_draft:
                domain += [
                    "|",
                    ("state", "=", "posted"),
                    "&",
                    ("state", "=", "draft"),
                    ("name", "not in", (False, "/")),
                ]
            else:
                domain.append(("state", "=", "posted"))
        return domain

    def _get_shared_sequence_values(self, move):
        for regex in KR_MOVE_SEQUENCE_REGEXES.values():
            match = re.fullmatch(regex, move.name or "")
            if not match:
                continue
            values = match.groupdict()
            if (
                int(values["seq"] or 0) > 0
                and values["year"] == move.date.strftime("%Y")
                and values["month"] == move.date.strftime("%m")
                and values["prefix2"] == move.date.strftime("%d")
                and bool(values["prefix1"])
                == (move.move_type in REFUND_MOVE_TYPES)
            ):
                return values
        return False

    def _get_duplicate_sequence_move_ids(self):
        """Keep one move and return later moves reusing the same daily number."""
        self.ensure_one()
        all_moves = self.env["account.move"].search(
            self._get_move_domain(ignore_journals=True),
            order="date, id",
        )
        moves_by_number = defaultdict(lambda: self.env["account.move"])
        for move in all_moves:
            values = self._get_shared_sequence_values(move)
            if values:
                key = (
                    move.date,
                    move.move_type in REFUND_MOVE_TYPES,
                    int(values["seq"]),
                )
                moves_by_number[key] |= move

        duplicate_ids = set()
        for grouped_moves in moves_by_number.values():
            if len(grouped_moves) < 2:
                continue
            keeper = min(
                grouped_moves,
                key=lambda move: (
                    bool(self._classify_move(move)[0]),
                    move.id,
                ),
            )
            duplicate_ids.update((grouped_moves - keeper).ids)
        return duplicate_ids

    def _classify_move(self, move):
        """Return the issue type and a user-facing explanation, or (False, False)."""
        self.ensure_one()
        rule = self.current_rule
        regex = KR_MOVE_SEQUENCE_REGEXES[rule]
        match = re.fullmatch(regex, move.name or "")
        if not match:
            if not move.name or move.name == "/" or move.sequence_number == 0:
                return "orphaned", _("번호가 없거나 순번을 인식할 수 없습니다.")
            return "format_mismatch", _("현재 선택한 전표번호 형식과 다릅니다.")

        values = match.groupdict()
        expected_refund = move.move_type in REFUND_MOVE_TYPES
        if int(values["seq"] or 0) < 1:
            return "orphaned", _("순번이 0이라 유효한 발급 번호로 볼 수 없습니다.")
        if (
            values["year"] != move.date.strftime("%Y")
            or values["month"] != move.date.strftime("%m")
            or values["prefix2"] != move.date.strftime("%d")
            or bool(values["prefix1"]) != expected_refund
        ):
            return "date_mismatch", _("번호의 날짜 또는 취소 구분이 전표와 다릅니다.")
        if rule == "date_number_type":
            expected_suffix = move.journal_id._kr_get_sequence_code()
            if values["suffix"] != expected_suffix:
                return "type_mismatch", _("번호의 전표유형 코드가 현재 저널 설정과 다릅니다.")
        return False, False

    def _sequence_group_key(self, move):
        return (
            move.date,
            move.move_type in REFUND_MOVE_TYPES,
        )

    def _format_proposed_name(self, move, sequence_number):
        refund_prefix = "R" if move.move_type in REFUND_MOVE_TYPES else ""
        proposed_name = "%s%s%06d" % (
            refund_prefix,
            move.date.strftime("%Y%m%d"),
            sequence_number,
        )
        if self.current_rule == "date_number_type":
            proposed_name += move.journal_id._kr_get_sequence_code()
        return proposed_name

    def _get_block_reason(self, move, proposed_name):
        if move.inalterable_hash:
            return _("해시로 보호된 전표이므로 번호를 변경할 수 없습니다.")
        if move.journal_id.sequence_override_regex:
            try:
                matches_override = re.match(
                    move.journal_id.sequence_override_regex, proposed_name
                )
            except re.error:
                return _("저널의 사용자 지정 정규식 자체가 올바르지 않습니다.")
            if not matches_override:
                return _("저널의 사용자 지정 정규식과 변경 예정 번호가 충돌합니다.")
        if move.state == "posted":
            try:
                move._check_fiscal_lock_dates()
                move.line_ids._check_tax_lock_date()
            except (UserError, ValidationError):
                return _("잠긴 회계기간의 전표이므로 번호를 변경할 수 없습니다.")
        return False

    def _build_preview_values(self, moves):
        self.ensure_one()
        duplicate_move_ids = self._get_duplicate_sequence_move_ids()
        next_by_group = defaultdict(int)
        seeded_groups = set()
        for move in moves:
            group_key = self._sequence_group_key(move)
            if group_key not in seeded_groups:
                next_by_group[group_key] = (
                    move._kr_get_last_shared_sequence_number()
                )
                seeded_groups.add(group_key)

        values_by_move = {}
        for move in moves.sorted(lambda item: (item.date, item.journal_id.id, item.id)):
            issue_type, issue_summary = self._classify_move(move)
            if not issue_type and move.id in duplicate_move_ids:
                issue_type = "duplicate_sequence"
                issue_summary = _(
                    "다른 전표유형과 같은 날짜·순번을 중복 사용하고 있습니다."
                )
            if not issue_type:
                continue
            group_key = self._sequence_group_key(move)
            next_by_group[group_key] += 1
            sequence_number = next_by_group[group_key]
            if sequence_number > 999999:
                proposed_name = False
                block_reason = _("해당 일자의 6자리 순번을 모두 사용했습니다.")
            else:
                proposed_name = self._format_proposed_name(move, sequence_number)
                block_reason = self._get_block_reason(move, proposed_name)
            values_by_move[move.id] = {
                "move_id": move.id,
                "current_name": move.name or "",
                "issue_type": issue_type,
                "issue_summary": issue_summary,
                "proposed_name": proposed_name,
                "result_state": "blocked" if block_reason else "ready",
                "result_message": block_reason or _("적용 준비 완료"),
            }

        # A ready target will release its current name during the atomic apply.
        # If that target later becomes blocked, repeat the collision check because
        # its current name must then be treated as occupied again.
        changed = True
        while changed:
            changed = False
            ready_ids = [
                move_id
                for move_id, vals in values_by_move.items()
                if vals["result_state"] == "ready"
            ]
            proposed_names = [
                vals["proposed_name"]
                for vals in values_by_move.values()
                if vals["result_state"] == "ready" and vals["proposed_name"]
            ]
            if not proposed_names:
                break
            collisions = self.env["account.move"].search([
                ("company_id", "=", self.company_id.id),
                ("name", "in", proposed_names),
                ("id", "not in", ready_ids),
            ])
            collision_keys = {
                (move.journal_id.id, move.name) for move in collisions
            }
            for move_id, vals in values_by_move.items():
                move = moves.browse(move_id)
                if (
                    vals["result_state"] == "ready"
                    and (move.journal_id.id, vals["proposed_name"])
                    in collision_keys
                ):
                    vals.update({
                        "result_state": "blocked",
                        "result_message": _("같은 저널에 변경 예정 번호가 이미 존재합니다."),
                    })
                    changed = True
        return list(values_by_move.values())

    def action_scan(self):
        self.ensure_one()
        self._check_account_manager()
        if self.date_from > self.date_to:
            raise UserError(_("시작일은 종료일보다 늦을 수 없습니다."))
        if not self.journal_ids:
            raise UserError(_("대상 저널을 하나 이상 선택해 주세요."))
        if self.current_rule not in ("date_number", "date_number_type"):
            raise UserError(_(
                "Odoo 기본은 이 모듈이 번호 형식을 정의하거나 수정하지 않는 설정입니다. "
                "날짜-번호 또는 날짜-번호-전표유형을 선택한 뒤 이 위저드를 사용하세요."
            ))

        moves = self.env["account.move"].search(
            self._get_move_domain(), order="date, journal_id, id"
        )
        preview_values = self._build_preview_values(moves)
        self.line_ids.unlink()
        self.write({
            "line_ids": [Command.create(vals) for vals in preview_values],
            "preview_rule": self.current_rule,
            "state": "preview",
            "result_message": False,
        })
        return False

    def action_reset(self):
        self.ensure_one()
        self._check_account_manager()
        self.line_ids.unlink()
        self.write({
            "state": "criteria",
            "preview_rule": False,
            "result_message": False,
        })
        return False

    def action_apply(self):
        self.ensure_one()
        self._check_account_manager()
        if self.state != "preview" or self.preview_rule != self.current_rule:
            raise UserError(_("설정이 변경되었습니다. 대상을 다시 조회해 주세요."))

        lines = self.line_ids.filtered(lambda line: line.result_state == "ready")
        if not lines:
            raise UserError(_("적용 가능한 전표가 없습니다."))
        if len(lines.mapped("move_id")) != len(lines):
            raise UserError(_("미리보기 대상에 중복 전표가 있습니다. 다시 조회해 주세요."))

        proposed_keys = [
            (line.journal_id.id, line.proposed_name) for line in lines
        ]
        if len(set(proposed_keys)) != len(proposed_keys):
            raise UserError(_("변경 예정 번호가 중복됩니다. 다시 조회해 주세요."))

        duplicate_move_ids = self._get_duplicate_sequence_move_ids()
        for line in lines:
            move = line.move_id
            if (move.name or "") != line.current_name:
                raise UserError(_(
                    "전표 '%(move)s'의 번호가 미리보기 후 변경되었습니다. 다시 조회해 주세요.",
                    move=move.display_name,
                ))
            issue_type, _issue_summary = self._classify_move(move)
            if not issue_type and move.id not in duplicate_move_ids:
                raise UserError(_("이미 정리된 전표가 있습니다. 다시 조회해 주세요."))
            block_reason = self._get_block_reason(move, line.proposed_name)
            if block_reason:
                raise UserError(block_reason)

        for line in lines:
            collision = self.env["account.move"].search([
                ("journal_id", "=", line.journal_id.id),
                ("name", "=", line.proposed_name),
                ("id", "not in", lines.move_id.ids),
            ], limit=1)
            if collision:
                raise UserError(_(
                    "변경 예정 번호 '%s'가 같은 저널에 이미 존재합니다. "
                    "대상을 다시 조회해 주세요.",
                    collision.name,
                ))

        repair_context = {
            "kr_sequence_repair_only_name": True,
            "skip_is_manually_modified": True,
            "tracking_disable": True,
            "mail_notrack": True,
        }
        moves = lines.move_id.with_context(**repair_context)
        moves.write({"name": False})
        moves.flush_recordset(["name"])
        for line in lines:
            line.move_id.with_context(**repair_context).write({
                "name": line.proposed_name,
            })
            line.write({
                "result_state": "applied",
                "result_message": _("변경 완료"),
            })

        self.write({
            "state": "done",
            "result_message": _(
                "전표번호 %(count)s건을 변경했습니다. 적용 불가 전표의 번호는 "
                "변경하지 않았습니다.",
                count=len(lines),
            ),
        })
        return False


class AccountKrMoveSequenceRepairLine(models.TransientModel):
    _name = "account.kr.move.sequence.repair.line"
    _description = "전표번호 소급 변경 적용 결과"
    _order = "id"

    wizard_id = fields.Many2one(
        comodel_name="account.kr.move.sequence.repair.wizard",
        required=True,
        ondelete="cascade",
    )
    move_id = fields.Many2one(
        comodel_name="account.move",
        string="전표",
        required=True,
        ondelete="cascade",
    )
    move_date = fields.Date(related="move_id.date", string="전표일자", readonly=True)
    journal_id = fields.Many2one(
        related="move_id.journal_id", string="저널", readonly=True
    )
    partner_id = fields.Many2one(
        related="move_id.partner_id", string="거래처", readonly=True
    )
    current_name = fields.Char(string="현재 전표번호", readonly=True)
    issue_type = fields.Selection(
        selection=[
            ("orphaned", "고아 번호"),
            ("format_mismatch", "형식 불일치"),
            ("date_mismatch", "날짜/취소 구분 불일치"),
            ("type_mismatch", "전표유형 불일치"),
            ("duplicate_sequence", "공통 순번 중복"),
        ],
        string="발견 유형",
        readonly=True,
    )
    issue_summary = fields.Char(string="판정 사유", readonly=True)
    proposed_name = fields.Char(string="변경 예정 번호", readonly=True)
    result_state = fields.Selection(
        selection=[
            ("ready", "적용 가능"),
            ("blocked", "적용 불가"),
            ("applied", "적용 완료"),
        ],
        string="처리 상태",
        readonly=True,
    )
    result_message = fields.Char(string="결과/사유", readonly=True)
