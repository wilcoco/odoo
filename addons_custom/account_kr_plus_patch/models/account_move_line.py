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
            "당좌예금 계정과목이 어느 실제 은행계좌에 해당하는지 지정합니다. "
            "은행저널의 기본 계정과 현재 계정과목이 같아야 합니다."
        ),
    )
    kr_bank_account_id = fields.Many2one(
        "res.partner.bank",
        string="은행 계좌번호",
        related="kr_bank_journal_id.bank_account_id",
        store=True,
        readonly=True,
    )

    @api.depends("account_id", "company_id", "move_id.journal_id")
    def _compute_kr_bank_journal_id(self):
        Journal = self.env["account.journal"]
        for line in self:
            if not line.account_id or line.account_id.account_type != "asset_cash":
                line.kr_bank_journal_id = False
                continue

            domain = [
                ("type", "=", "bank"),
                ("company_id", "=", line.company_id.id),
                ("default_account_id", "=", line.account_id.id),
            ]
            current = line.kr_bank_journal_id
            if (
                current
                and current.type == "bank"
                and current.company_id == line.company_id
                and current.default_account_id == line.account_id
            ):
                continue

            candidates = Journal.search(domain, limit=2)

            move_journal = line.move_id.journal_id
            if (
                move_journal.type == "bank"
                and move_journal.default_account_id == line.account_id
            ):
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
