from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

from .res_company import KR_MOVE_SEQUENCE_RULES


KR_FREQUENT_OPTIONAL_SETTINGS = {
    "asset_models": {
        "name": "자산 모델",
        "module_names": ("account_asset",),
        "xmlids": (
            "account_asset.action_account_asset_model",
            "account_asset.action_account_asset_model_form",
        ),
        "res_model": "account.asset",
        "action_tokens": ("asset_model",),
        "domain": [("state", "=", "model")],
        "context": {"default_state": "model"},
    },
    "account_reports": {
        "name": "회계 보고서 설정",
        "module_names": ("account_reports",),
        "xmlids": (
            "account_reports.action_account_report",
            "account_reports.action_account_report_form",
        ),
        "res_model": "account.report",
        "action_tokens": ("account_report",),
    },
    "disallowed_expense_categories": {
        "name": "손금불산입 카테고리",
        "module_names": ("account_disallowed_expenses",),
        "xmlids": (
            "account_disallowed_expenses.action_account_disallowed_expenses_category",
            "account_disallowed_expenses.account_disallowed_expenses_category_action",
        ),
        "res_model": "account.disallowed.expenses.category",
        "action_tokens": ("disallowed", "category"),
    },
}


class AccountKrPlusSettings(models.Model):
    _name = "account.kr.plus.settings"
    _description = "한국식 회계 설정"
    _rec_name = "singleton_key"

    _sql_constraints = [
        (
            "account_kr_plus_settings_singleton_uniq",
            "unique(singleton_key)",
            "한국식 회계 설정은 하나만 존재할 수 있습니다.",
        ),
        (
            "account_kr_plus_settings_singleton_check",
            "CHECK(singleton_key = 'global')",
            "한국식 회계 설정은 전역 단일 항목이어야 합니다.",
        ),
    ]

    singleton_key = fields.Char(
        string="설정 키",
        required=True,
        default="global",
        readonly=True,
        copy=False,
    )

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
        settings = super().create([
            self._normalize_legacy_sequence_values(vals) for vals in vals_list
        ])
        settings._apply_global_rule()
        return settings

    def write(self, vals):
        vals = self._normalize_legacy_sequence_values(vals)
        result = super().write(vals)
        if "kr_move_sequence_rule" in vals:
            self._apply_global_rule()
        return result

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

    @api.model
    def _get_global_settings(self):
        settings = self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global",
            raise_if_not_found=False,
        )
        if settings and settings.exists():
            return settings
        return self.sudo().search([("singleton_key", "=", "global")], limit=1)

    @api.model
    def _get_global_rule(self):
        settings = self.sudo()._get_global_settings()
        return settings.kr_move_sequence_rule if settings else "odoo"

    def _apply_global_rule(self):
        self.ensure_one()
        self.env["res.company"].sudo().search([]).write({
            "kr_move_sequence_rule": self.kr_move_sequence_rule,
        })

    def action_save(self):
        self.ensure_one()
        self._check_account_manager()
        self._apply_global_rule()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("설정 저장 완료"),
                "message": _(
                    "전역 전표번호 설정을 저장했습니다. "
                    "이미 발급된 전표번호는 변경되지 않습니다."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def action_open_sequence_journals(self):
        self.ensure_one()
        self._check_account_manager()
        company = self.env.company
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
            "domain": [("company_id", "=", company.id)],
            "context": {"default_company_id": company.id},
        }

    def action_open_sequence_repair(self):
        self.ensure_one()
        self._check_account_manager()
        # 폼에서 형식을 바꾼 직후 버튼을 눌러도 이전 전역 설정을 읽지 않도록
        # 현재 선택값을 먼저 모든 회사에 반영한 뒤 위저드를 연다.
        self._apply_global_rule()
        if self.kr_move_sequence_rule == "odoo":
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("한국식 전표번호 형식을 선택해 주세요"),
                    "message": _(
                        "Odoo 기본은 소급 변경할 번호 형식을 정의하지 않습니다. "
                        "날짜-번호 또는 날짜-번호-전표유형을 저장한 뒤 실행해 주세요."
                    ),
                    "type": "warning",
                    "sticky": True,
                },
            }
        company = self.env.company
        return {
            "type": "ir.actions.act_window",
            "name": _("전표번호 소급 변경 적용"),
            "res_model": "account.kr.move.sequence.repair.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "account_kr_plus_patch.view_account_kr_move_sequence_repair_wizard_form"
            ).id,
            "target": "new",
            "context": {"default_company_id": company.id},
        }

    def action_open_bank_journals(self):
        self.ensure_one()
        self._check_account_manager()
        company = self.env.company
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account_kr_plus_patch.action_kr_bank_journals"
        )
        action["domain"] = [
            ("company_id", "=", company.id),
            ("type", "=", "bank"),
        ]
        action["context"] = {
            "default_company_id": company.id,
            "default_type": "bank",
            "kr_bank_account_setup": True,
        }
        return action

    def action_open_accounts(self):
        self.ensure_one()
        self._check_account_manager()
        company = self.env.company
        action = self.env["ir.actions.actions"]._for_xml_id(
            "account.action_account_form"
        )
        action["domain"] = [("company_ids", "in", company.ids)]
        return action

    @api.model
    def action_open_frequent_optional_setting(self, target):
        """Open an Enterprise/optional setting without making it a dependency."""
        self._check_account_manager()
        config = KR_FREQUENT_OPTIONAL_SETTINGS.get(target)
        if not config:
            raise UserError(_("알 수 없는 자주 쓰는 설정 항목입니다."))

        for xmlid in config["xmlids"]:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if (
                action
                and action.exists()
                and action._name.startswith("ir.actions.")
            ):
                return action._get_action_dict()

        actions = self.env["ir.actions.act_window"].sudo().search([
            ("res_model", "=", config["res_model"]),
        ])
        external_ids = actions.get_external_id()
        for action in actions:
            xmlid = external_ids.get(action.id, "").lower()
            if all(token in xmlid for token in config["action_tokens"]):
                return action._get_action_dict()
        if len(actions) == 1:
            return actions._get_action_dict()

        installed = self.env["ir.module.module"].sudo().search_count([
            ("name", "in", config["module_names"]),
            ("state", "=", "installed"),
        ])
        if installed and config["res_model"] in self.env:
            return {
                "type": "ir.actions.act_window",
                "name": config["name"],
                "res_model": config["res_model"],
                "view_mode": "list,form",
                "domain": config.get("domain", []),
                "context": config.get("context", {}),
            }

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("선택 모듈이 필요합니다"),
                "message": _(
                    "'%(setting)s' 화면을 제공하는 모듈이 설치되어 있는지 "
                    "확인해 주세요.",
                    setting=config["name"],
                ),
                "type": "warning",
                "sticky": False,
            },
        }
