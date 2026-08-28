from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from .res_company import KR_MOVE_SEQUENCE_FORMATS


class AccountKrPlusSettings(models.TransientModel):
    _name = "account.kr.plus.settings"
    _description = "한국식 회계 설정"

    company_id = fields.Many2one(
        comodel_name="res.company",
        string="회사",
        required=True,
        default=lambda self: self.env.company,
        domain=lambda self: [("id", "in", self.env.companies.ids)],
    )
    kr_use_custom_move_sequence = fields.Boolean(
        string="한국식 전표번호 규칙 사용",
        default=lambda self: self.env.company.kr_use_custom_move_sequence,
    )
    kr_move_sequence_format = fields.Selection(
        selection=KR_MOVE_SEQUENCE_FORMATS,
        string="전표번호 형식",
        required=True,
        default=lambda self: self.env.company.kr_move_sequence_format,
    )
    sequence_example = fields.Char(
        string="번호 예시",
        compute="_compute_sequence_example",
    )

    @api.depends("kr_use_custom_move_sequence", "kr_move_sequence_format")
    def _compute_sequence_example(self):
        for settings in self:
            if not settings.kr_use_custom_move_sequence:
                settings.sequence_example = _("Odoo 저널 기본 번호 사용")
            else:
                settings.sequence_example = (
                    "R20260828000001-PURCHASE"
                    if settings.kr_move_sequence_format == "extended"
                    else "R20260828000001PUR"
                )

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if self.company_id:
            self.kr_use_custom_move_sequence = (
                self.company_id.kr_use_custom_move_sequence
            )
            self.kr_move_sequence_format = self.company_id.kr_move_sequence_format

    def _check_account_manager(self):
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError(_("회계 관리자만 한국식 회계 설정을 변경할 수 있습니다."))
        if self.company_id and self.company_id.id not in self.env.companies.ids:
            raise AccessError(_("접근할 수 없는 회사의 회계 설정은 변경할 수 없습니다."))

    def action_save(self):
        self.ensure_one()
        self._check_account_manager()
        # res.company 전체 쓰기 권한을 부여하지 않고 이 설정 필드만 제한적으로 저장한다.
        self.company_id.sudo().write({
            "kr_use_custom_move_sequence": self.kr_use_custom_move_sequence,
            "kr_move_sequence_format": self.kr_move_sequence_format,
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("설정 저장 완료"),
                "message": _(
                    "선택한 회사의 전표번호 설정을 저장했습니다. "
                    "이미 발급된 전표번호는 변경되지 않습니다."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def action_open_sequence_journals(self):
        self.ensure_one()
        self._check_account_manager()
        return {
            "type": "ir.actions.act_window",
            "name": _("저널·전표유형 코드"),
            "res_model": "account.journal",
            "view_mode": "list,form",
            "views": [
                (self.env.ref(
                    "account_kr_plus_patch.view_kr_sequence_journal_list"
                ).id, "list"),
                (self.env.ref("account.view_account_journal_form").id, "form"),
            ],
            "domain": [("company_id", "=", self.company_id.id)],
            "context": {"default_company_id": self.company_id.id},
        }

    def action_open_bank_journals(self):
        self.ensure_one()
        self._check_account_manager()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account_kr_plus_patch.action_kr_bank_journals"
        )
        action["domain"] = [
            ("company_id", "=", self.company_id.id),
            ("type", "=", "bank"),
        ]
        action["context"] = {
            "default_company_id": self.company_id.id,
            "default_type": "bank",
        }
        return action

    def action_open_accounts(self):
        self.ensure_one()
        self._check_account_manager()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_account_form"
        )
        action["domain"] = [("company_ids", "in", self.company_id.ids)]
        return action
