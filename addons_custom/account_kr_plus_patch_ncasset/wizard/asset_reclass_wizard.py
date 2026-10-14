from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command


class AccountAssetKrReclassWizard(models.TransientModel):
    """자산별 계정으로 원장 잔액을 옮기는 **초안** 재분류 전표를 만든다.

    전표는 초안으로만 만들고 절대 전기하지 않는다. 이미 검증이 끝난 기간을 소급해서
    건드리지 않도록, 전표 일자는 담당자가 직접 정하고 결과를 확인한 뒤 사람이 전기한다.
    """

    _name = "account.asset.kr.reclass.wizard"
    _description = "자산별 계정 재분류(초안 전표)"

    asset_ids = fields.Many2many("account.asset", string="자산", required=True)
    company_id = fields.Many2one(
        "res.company", string="회사", required=True, default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="저널",
        required=True,
        domain="[('type', '=', 'general')]",
        default=lambda self: self.env.company.kr_asset_reclass_journal_id,
    )
    date = fields.Date(string="전표 일자", required=True, default=fields.Date.context_today)
    source_account_id = fields.Many2one(
        "account.account",
        string="옮길 원 계정",
        required=True,
        help="현재 잔액이 쌓여 있는 계정입니다(예: 토지 기준 계정).",
    )
    ref = fields.Char(string="적요", default="자산별 계정 재분류")

    @api.onchange("asset_ids")
    def _onchange_asset_ids(self):
        if self.asset_ids and not self.source_account_id:
            bases = self.asset_ids.kr_account_ids.filtered(lambda line: line.kind == "asset").base_account_id
            if len(bases) == 1:
                self.source_account_id = bases

    def action_create_draft_move(self):
        self.ensure_one()
        if not self.asset_ids:
            raise UserError(_("자산을 선택하세요."))
        lines = []
        total = 0.0
        for asset in self.asset_ids:
            target = asset.kr_account_ids.filtered(lambda line: line.kind == "asset").account_id
            if not target:
                raise UserError(
                    _("자산 ‘%s’ 에 자산별 계정이 없습니다. 먼저 자산별 계정을 만드세요.", asset.name)
                )
            if target == self.source_account_id:
                raise UserError(
                    _("자산 ‘%s’ 의 자산별 계정이 원 계정과 같습니다.", asset.name)
                )
            amount = asset.original_value
            if not amount:
                continue
            total += amount
            lines.append(
                Command.create(
                    {
                        "account_id": target.id,
                        "name": _("%s 재분류", asset.name),
                        "debit": amount,
                        "credit": 0.0,
                    }
                )
            )
        if not lines:
            raise UserError(_("재분류할 금액이 없습니다."))
        lines.append(
            Command.create(
                {
                    "account_id": self.source_account_id.id,
                    "name": self.ref or _("자산별 계정 재분류"),
                    "debit": 0.0,
                    "credit": total,
                }
            )
        )
        move = self.env["account.move"].create(
            {
                "move_type": "entry",
                "journal_id": self.journal_id.id,
                "date": self.date,
                "ref": self.ref,
                "company_id": self.company_id.id,
                "line_ids": lines,
            }
        )
        move.message_post(
            body=_(
                "자산별 계정 재분류 초안입니다. 내용을 확인한 뒤 <b>사람이 직접 전기</b>하세요. "
                "이미 검증이 끝난 기간으로 소급하지 않도록 일자를 확인하세요."
            )
        )
        return {
            "name": _("재분류 전표(초안)"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": move.id,
            "view_mode": "form",
        }
