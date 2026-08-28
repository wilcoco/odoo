from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from .res_company import KR_MOVE_SEQUENCE_RULES


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
    kr_move_sequence_rule = fields.Selection(
        selection=KR_MOVE_SEQUENCE_RULES,
        string="전표번호 형식",
        required=True,
        default=lambda self: self.env.company.kr_move_sequence_rule or "odoo",
    )
    # Keep the removed 18.0.2.1.0 field names as non-stored aliases.  A server
    # restart can load the new Python model before the module upgrade replaces
    # the view stored in ir_ui_view.  Without these aliases that short-lived
    # mixed state makes the legacy view's onchange fail with a KeyError.
    kr_use_custom_move_sequence = fields.Boolean(
        string="한국식 전표번호 규칙 사용 (호환용)",
        store=False,
        default=lambda self: (
            self.env.company.kr_move_sequence_rule or "odoo"
        ) != "odoo",
    )
    kr_move_sequence_format = fields.Selection(
        selection=KR_MOVE_SEQUENCE_RULES,
        string="전표번호 형식 (호환용)",
        store=False,
        default=lambda self: self.env.company.kr_move_sequence_rule or "odoo",
    )
    sequence_example = fields.Char(
        string="번호 예시",
        compute="_compute_sequence_example",
    )

    @api.depends("kr_move_sequence_rule")
    def _compute_sequence_example(self):
        for settings in self:
            examples = {
                "date_number": "R20260828000001",
                "date_number_type": "R20260828000001PUR",
                "odoo": _("Odoo 저널 기본 번호 사용"),
            }
            settings.sequence_example = examples.get(
                settings.kr_move_sequence_rule, examples["odoo"]
            )

    @api.onchange("company_id")
    def _onchange_company_id(self):
        if self.company_id:
            self.kr_move_sequence_rule = (
                self.company_id.kr_move_sequence_rule or "odoo"
            )
            self.kr_move_sequence_format = self.kr_move_sequence_rule
            self.kr_use_custom_move_sequence = (
                self.kr_move_sequence_rule != "odoo"
            )

    @api.onchange("kr_move_sequence_format", "kr_use_custom_move_sequence")
    def _onchange_legacy_sequence_fields(self):
        """Let a cached legacy settings form safely update the new rule."""
        if not self.kr_use_custom_move_sequence:
            self.kr_move_sequence_rule = "odoo"
            self.kr_move_sequence_format = "odoo"
        else:
            if self.kr_move_sequence_format not in dict(KR_MOVE_SEQUENCE_RULES):
                self.kr_move_sequence_format = "date_number"
            elif self.kr_move_sequence_format == "odoo":
                self.kr_move_sequence_format = "date_number"
            self.kr_move_sequence_rule = self.kr_move_sequence_format

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([
            self._normalize_legacy_sequence_values(vals) for vals in vals_list
        ])

    def write(self, vals):
        return super().write(self._normalize_legacy_sequence_values(vals))

    @api.model
    def _normalize_legacy_sequence_values(self, vals):
        """Translate values submitted by the pre-18.0.2.2.0 settings view."""
        vals = dict(vals)
        if "kr_move_sequence_rule" in vals:
            canonical_rule = vals["kr_move_sequence_rule"]
            if "kr_move_sequence_format" in vals:
                vals["kr_move_sequence_format"] = canonical_rule
            if "kr_use_custom_move_sequence" in vals:
                vals["kr_use_custom_move_sequence"] = (
                    canonical_rule != "odoo"
                )
            return vals

        enabled = vals.get("kr_use_custom_move_sequence")
        legacy_rule = vals.get("kr_move_sequence_format")
        if enabled is False:
            vals["kr_move_sequence_rule"] = "odoo"
        elif legacy_rule:
            # Old browser state may still submit the former selection keys.
            mapped_rule = {
                "legacy": "date_number_type",
                "extended": "odoo",
            }.get(legacy_rule, legacy_rule)
            if mapped_rule not in dict(KR_MOVE_SEQUENCE_RULES):
                mapped_rule = "odoo"
            vals["kr_move_sequence_rule"] = mapped_rule
            vals["kr_move_sequence_format"] = mapped_rule
        elif enabled is True:
            vals["kr_move_sequence_rule"] = "date_number"
            vals["kr_move_sequence_format"] = "date_number"
        return vals

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
            "kr_move_sequence_rule": self.kr_move_sequence_rule,
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
            "name": _("전표유형 및 코드 설정"),
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

    def action_open_sequence_repair(self):
        self.ensure_one()
        self._check_account_manager()
        return {
            "type": "ir.actions.act_window",
            "name": _("전표번호 점검 및 수정"),
            "res_model": "account.kr.move.sequence.repair.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "account_kr_plus_patch.view_account_kr_move_sequence_repair_wizard_form"
            ).id,
            "target": "new",
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
