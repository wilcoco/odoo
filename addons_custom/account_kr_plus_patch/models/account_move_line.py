from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    kr_bank_journal_id = fields.Many2one(
        "account.journal",
        string="연결 은행계좌",
        compute="_compute_kr_bank_journal_id",
        inverse="_inverse_kr_bank_journal_id",
        store=True,
        readonly=False,
        copy=False,
        check_company=True,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id), "
               "('default_account_id', '=', account_id)]",
        help=(
            "예금·단기금융상품 계정과목이 어느 실제 은행계좌에 해당하는지 "
            "지정합니다. 은행저널의 기본 계정과 현재 계정과목이 같아야 합니다."
        ),
    )
    kr_bank_account_id = fields.Many2one(
        "res.partner.bank",
        string="은행 계좌번호",
        related="kr_bank_journal_id.bank_account_id",
        store=True,
        readonly=True,
    )

    @api.model
    def _kr_bank_journals_by_account(self, companies):
        """{(회사, 계정과목): 은행저널} 매핑 — 라인마다 검색하지 않는다.

        계정유형이 아니라 '어떤 은행저널의 계정과목인가'로 판단하므로,
        단기금융상품(MMT 등)을 유동자산 계정으로 둔 은행저널도 인식한다.
        """
        mapping = {}
        journals = self.env["account.journal"].sudo().search([
            ("type", "=", "bank"),
            ("company_id", "in", companies.ids),
            ("default_account_id", "!=", False),
        ])
        for journal in journals:
            key = (journal.company_id.id, journal.default_account_id.id)
            mapping.setdefault(key, self.env["account.journal"])
            mapping[key] |= journal
        return mapping

    @api.depends("account_id", "company_id", "move_id.journal_id")
    def _compute_kr_bank_journal_id(self):
        mapping = self._kr_bank_journals_by_account(self.company_id)
        for line in self:
            candidates = mapping.get(
                (line.company_id.id, line.account_id.id)
            ) or self.env["account.journal"]
            if not candidates:
                line.kr_bank_journal_id = False
                continue

            current = line.kr_bank_journal_id
            if current and current in candidates:
                continue

            move_journal = line.move_id.journal_id
            if move_journal in candidates:
                line.kr_bank_journal_id = move_journal
            elif len(candidates) == 1:
                line.kr_bank_journal_id = candidates
            else:
                # 둘 이상이면 사용자가 실제 은행계좌를 선택해야 한다.
                line.kr_bank_journal_id = False

    def _inverse_kr_bank_journal_id(self):
        # 사용자가 선택한 값은 다음 계정과목 변경 전까지 그대로 보존한다.
        return

    @api.constrains("account_id", "kr_bank_journal_id", "company_id")
    def _check_kr_bank_journal_matches_account(self):
        for line in self.filtered("kr_bank_journal_id"):
            journal = line.kr_bank_journal_id
            if journal.type != "bank":
                raise ValidationError(_("연결 은행계좌에는 은행 유형 저널만 선택할 수 있습니다."))
            if journal.default_account_id != line.account_id:
                raise ValidationError(_(
                    "연결 은행계좌 '%(journal)s'의 기본 계정과 현재 계정과목 "
                    "'%(account)s'이 일치하지 않습니다.",
                    journal=journal.display_name,
                    account=line.account_id.display_name,
                ))
