from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestAccountKrPlusPatch(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.misc_journal = cls.env["account.journal"].create({
            "name": "한국식 전표 테스트",
            "code": "KRT",
            "type": "general",
            "company_id": cls.company_data["company"].id,
            "kr_sequence_code": "GEN",
        })
        cls.other_misc_journal = cls.env["account.journal"].create({
            "name": "한국식 전표 유형 교차 테스트",
            "code": "KRS",
            "type": "general",
            "company_id": cls.company_data["company"].id,
            "kr_sequence_code": "SAL",
        })

    def _create_entry(
        self, move_date, debit_account=None, bank_journal=None, journal=None
    ):
        debit_account = debit_account or self.company_data["default_account_expense"]
        debit_values = {
            "name": "첫 번째 적요",
            "account_id": debit_account.id,
            "debit": 100.0,
        }
        if bank_journal:
            debit_values["kr_bank_journal_id"] = bank_journal.id
        return self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": (journal or self.misc_journal).id,
            "date": fields.Date.to_date(move_date),
            "line_ids": [
                Command.create(debit_values),
                Command.create({
                    "name": "상대 계정",
                    "account_id": self.company_data["default_account_revenue"].id,
                    "credit": 100.0,
                }),
            ],
        })

    def _enable_custom_sequence(self, sequence_rule="date_number_type"):
        self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global"
        ).write({
            "kr_move_sequence_rule": sequence_rule,
        })

    def test_standard_sequence_is_default_for_new_vendor_bill(self):
        self.assertEqual(
            self.company_data["company"].kr_move_sequence_rule,
            "odoo",
        )
        bill = self.env["account.move"].new({
            "move_type": "in_invoice",
            "journal_id": self.company_data["default_journal_purchase"].id,
            "date": fields.Date.to_date("2024-07-18"),
            "invoice_date": fields.Date.to_date("2024-07-18"),
        })

        self.assertFalse(bill._kr_uses_configured_sequence())
        starting_sequence = bill._get_starting_sequence()
        self.assertEqual(
            bill._deduce_sequence_number_reset(starting_sequence),
            "month",
        )

    def test_sequence_setting_has_only_requested_choices(self):
        choices = self.company_data["company"]._fields[
            "kr_move_sequence_rule"
        ]._description_selection(self.env)
        self.assertEqual(
            choices,
            [
                ("date_number", "날짜-번호"),
                ("date_number_type", "날짜-번호-전표유형"),
                ("odoo", "Odoo 기본 (관여하지 않음)"),
            ],
        )

    def test_settings_are_one_persistent_global_record(self):
        settings_model = self.env["account.kr.plus.settings"]
        settings = self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global"
        )
        action = self.env.ref(
            "account_kr_plus_patch.action_account_kr_plus_settings"
        )

        self.assertFalse(settings_model.is_transient())
        self.assertEqual(settings_model.search_count([]), 1)
        self.assertEqual(action.res_id, settings.id)

    def test_global_setting_is_applied_to_every_company(self):
        self._enable_custom_sequence("date_number")

        self.assertEqual(
            set(self.env["res.company"].sudo().search([]).mapped(
                "kr_move_sequence_rule"
            )),
            {"date_number"},
        )
        move = self._create_entry("2024-07-30")
        self.assertEqual(move._kr_get_configured_sequence_rule(), "date_number")

    def test_opening_retroactive_rename_applies_selected_rule_first(self):
        settings = self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global"
        ).with_user(self.simple_accountman)
        settings.write({"kr_move_sequence_rule": "date_number"})

        action = settings.action_open_sequence_repair()

        self.assertEqual(
            set(self.env["res.company"].sudo().search([]).mapped(
                "kr_move_sequence_rule"
            )),
            {"date_number"},
        )
        self.assertEqual(action["name"], "전표번호 소급 변경 적용")

    def test_odoo_default_does_not_open_retroactive_rename(self):
        settings = self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global"
        ).with_user(self.simple_accountman)
        settings.write({"kr_move_sequence_rule": "odoo"})

        action = settings.action_open_sequence_repair()

        self.assertEqual(action["tag"], "display_notification")
        self.assertEqual(
            set(self.env["res.company"].sudo().search([]).mapped(
                "kr_move_sequence_rule"
            )),
            {"odoo"},
        )

    def test_invoice_lists_distinguish_collection_and_disbursement(self):
        action = self.env.ref(
            "account_kr_plus_patch.action_kr_journal_entries"
        )
        self.assertEqual(action.domain, "[]")

        journal_list_arch = self.env.ref(
            "account_kr_plus_patch.view_move_tree_kr_operational_summary"
        ).arch_db
        for field_name in (
            "kr_move_number_display",
            "kr_primary_partner_id",
            "kr_primary_label",
            "kr_primary_reference",
            "kr_bank_journal_ids",
        ):
            self.assertIn('name="%s"' % field_name, journal_list_arch)
        self.assertIn('string="보통예금 종류"', journal_list_arch)
        self.assertIn('name="kr_bank_journal_ids"', journal_list_arch)
        self.assertIn('optional="show"', journal_list_arch)

        customer_arch = self.env.ref(
            "account_kr_plus_patch.view_kr_customer_tax_invoice_list"
        ).arch_db
        vendor_arch = self.env.ref(
            "account_kr_plus_patch.view_kr_vendor_tax_invoice_list"
        ).arch_db

        for arch in (customer_arch, vendor_arch):
            self.assertIn('name="kr_move_number_display"', arch)
            self.assertIn('name="name" column_invisible="True"', arch)
            self.assertIn('name="status_in_payment"', arch)
            self.assertIn('name="kr_doc_type"', arch)
            self.assertIn('name="kr_tax_type"', arch)
            self.assertLess(
                arch.index('name="kr_residual_display"'),
                arch.index('name="invoice_date_due"'),
            )
            self.assertLess(
                arch.index('name="invoice_date_due"'),
                arch.index('name="kr_paid_amount"'),
            )
            self.assertLess(
                arch.index('name="kr_paid_amount"'),
                arch.index('name="status_in_payment"'),
            )

        self.assertIn('string="미수금액"', customer_arch)
        self.assertIn('string="수금기한"', customer_arch)
        self.assertIn('string="수금완료 금액"', customer_arch)
        self.assertIn('string="수금상태"', customer_arch)
        self.assertNotIn('name="pumui_id"', customer_arch)

        self.assertIn('name="pumui_id" string="품의서"', vendor_arch)
        self.assertIn('string="품의 결재상태"', vendor_arch)
        self.assertIn('string="미지급금액"', vendor_arch)
        self.assertIn('string="지급기한"', vendor_arch)
        self.assertIn('string="지급완료 금액"', vendor_arch)
        self.assertIn('string="지급상태"', vendor_arch)
        self.assertLess(
            vendor_arch.index('name="pumui_id"'),
            vendor_arch.index('name="kr_approval_status_display"'),
        )
        self.assertLess(
            vendor_arch.index('name="kr_approval_status_display"'),
            vendor_arch.index('name="kr_residual_display"'),
        )

        search_arch = self.env.ref(
            "account_kr_plus_patch.view_kr_vendor_tax_invoice_search"
        ).arch_db
        self.assertIn('name="no_pumui"', search_arch)
        self.assertIn('name="approval_pending"', search_arch)
        self.assertIn('name="group_approval"', search_arch)

        self.assertEqual(
            self.env.ref("account.menu_action_move_out_invoice_type").action.id,
            self.env.ref(
                "account_kr_plus_patch.action_kr_customer_tax_invoice"
            ).id,
        )
        self.assertEqual(
            self.env.ref("account.menu_action_move_in_invoice_type").action.id,
            self.env.ref(
                "account_kr_plus_patch.action_kr_vendor_tax_invoice"
            ).id,
        )
        for action_xmlid, list_xmlid, search_xmlid in (
            (
                "account.action_move_out_invoice_type",
                "account_kr_plus_patch.view_kr_customer_tax_invoice_list",
                "account_kr_plus_patch.view_kr_customer_tax_invoice_search",
            ),
            (
                "account.action_move_in_invoice_type",
                "account_kr_plus_patch.view_kr_vendor_tax_invoice_list",
                "account_kr_plus_patch.view_kr_vendor_tax_invoice_search",
            ),
        ):
            dashboard_action = self.env.ref(action_xmlid)
            self.assertIn(
                self.env.ref(list_xmlid),
                dashboard_action.view_ids.mapped("view_id"),
            )
            self.assertEqual(
                dashboard_action.search_view_id,
                self.env.ref(search_xmlid),
            )

        payment_tail_arch = self.env.ref(
            "account_kr_plus_patch.view_invoice_tree_kr_payment_tail"
        ).arch_db
        self.assertIn(
            'expr="//field[@name=\'invoice_date_due\']" position="move"',
            payment_tail_arch,
        )
        self.assertIn(
            'expr="//field[@name=\'status_in_payment\']" position="move"',
            payment_tail_arch,
        )

        form_arch = self.env.ref(
            "account_kr_plus_patch.view_move_form_kr_plus"
        ).arch_db
        self.assertNotIn('string="청구서(세금계산서)"', form_arch)
        self.assertIn('name="ref" string="참조"', form_arch)
        self.assertIn('name="kr_approval_number"', form_arch)
        self.assertIn('string="세금계산서승인번호"', form_arch)
        self.assertIn('name="kr_origin_number"', form_arch)
        self.assertIn('string="원본 세금계산서 승인번호"', form_arch)
        self.assertIn('name="kr_move_number_display"', form_arch)
        self.assertIn('name="name" invisible="1"', form_arch)
        self.assertIn('name="pumui_id" string="품의서"', form_arch)
        self.assertIn('string="품의 결재상태"', form_arch)
        self.assertNotIn('name="other_info"', form_arch)

        cleanup_arch = self.env.ref(
            "account_kr_plus_patch.view_move_form_kr_hide_unused_invoice_info"
        ).arch_db
        for field_name in (
            "delivery_date",
            "invoice_incoterm_id",
            "incoterm_location",
            "qr_code_method",
            "invoice_cash_rounding_id",
            "invoice_source_email",
            "auto_post",
            "auto_post_until",
            "checked",
        ):
            self.assertIn("@name='%s'" % field_name, cleanup_arch)

        settings_arch = self.env.ref(
            "account_kr_plus_patch.view_account_kr_plus_settings_form"
        ).arch_db
        self.assertIn('string="전표 설정"', settings_arch)
        self.assertIn('string="전표유형 및 코드 설정"', settings_arch)
        self.assertIn('string="전표번호 소급 변경 적용"', settings_arch)
        self.assertIn('string="계좌 설정"', settings_arch)

    def test_legacy_approval_status_field_remains_for_saved_views(self):
        move = self._create_entry("2024-07-17")
        self.assertEqual(move.kr_approval_status_display, "미연결")

    def test_daily_compact_sequence(self):
        self._enable_custom_sequence()
        first = self._create_entry("2024-07-18")
        second = self._create_entry("2024-07-18")
        next_day = self._create_entry("2024-07-19")

        first.action_post()
        second.action_post()
        next_day.action_post()

        self.assertEqual(first.name, "20240718000001GEN")
        self.assertEqual(second.name, "20240718000002GEN")
        self.assertEqual(next_day.name, "20240719000001GEN")

    def test_draft_number_uses_friendly_display_until_posting(self):
        move = self._create_entry("2024-07-18")

        self.assertEqual(move.name, "/")
        self.assertEqual(move.kr_move_number_display, "전기 시 자동 생성")

        move.action_post()
        self.assertNotEqual(move.name, "/")
        self.assertEqual(move.kr_move_number_display, move.name)

    def test_journal_list_summaries_use_first_available_content(self):
        first_partner = self.env["res.partner"].create({"name": "첫 거래처"})
        second_partner = self.env["res.partner"].create({"name": "둘째 거래처"})
        move = self._create_entry("2024-07-18")
        lines = move.line_ids.sorted(lambda line: (line.sequence, line.id))
        lines[0].write({"partner_id": first_partner.id, "name": False})
        lines[1].write({"partner_id": second_partner.id, "name": "첫 유효 적요"})
        move.ref = "전표 참조"

        self.assertEqual(move.kr_primary_partner_id, first_partner)
        self.assertEqual(move.kr_primary_label, "첫 유효 적요")
        self.assertEqual(move.kr_primary_reference, "전표 참조")

        move.kr_primary_label = "수정한 적요"
        self.assertEqual(lines[1].name, "수정한 적요")

        move.write({"ref": False, "invoice_origin": "원본 문서"})
        self.assertEqual(move.kr_primary_reference, "원본 문서")

    def test_daily_date_number_sequence_without_type_code(self):
        self._enable_custom_sequence("date_number")
        move = self._create_entry("2024-07-18")
        move.action_post()

        self.assertEqual(move.name, "20240718000001")

    def test_first_customer_and_vendor_invoice_accept_date_number_rule(self):
        self._enable_custom_sequence("date_number")
        invoice_date = fields.Date.to_date("2099-12-31")

        for move_type, journal in (
            ("out_invoice", self.company_data["default_journal_sale"]),
            ("in_invoice", self.company_data["default_journal_purchase"]),
        ):
            invoice = self.env["account.move"].new({
                "move_type": move_type,
                "journal_id": journal.id,
                "company_id": self.company_data["company"].id,
                "invoice_date": invoice_date,
                "date": invoice_date,
            })

            self.assertEqual(
                invoice._deduce_sequence_number_reset(False),
                "month",
            )
            self.assertEqual(
                invoice._get_accounting_date(invoice_date, False),
                invoice_date,
            )

    def test_daily_sequence_is_shared_across_ttt_codes(self):
        self._enable_custom_sequence()
        general_move = self._create_entry("2024-07-26")
        sale_code_move = self._create_entry(
            "2024-07-26", journal=self.other_misc_journal
        )
        next_general_move = self._create_entry("2024-07-26")

        general_move.action_post()
        sale_code_move.action_post()
        next_general_move.action_post()

        self.assertEqual(general_move.name, "20240726000001GEN")
        self.assertEqual(sale_code_move.name, "20240726000002SAL")
        self.assertEqual(next_general_move.name, "20240726000003GEN")
        self.assertFalse(any(
            (general_move | sale_code_move | next_general_move).mapped(
                "made_sequence_gap"
            )
        ))

    def test_daily_sequence_is_shared_between_journals_with_same_ttt(self):
        self._enable_custom_sequence()
        self.other_misc_journal.kr_sequence_code = "GEN"
        first = self._create_entry("2024-07-29")
        second = self._create_entry(
            "2024-07-29", journal=self.other_misc_journal
        )

        first.action_post()
        second.action_post()

        self.assertEqual(first.name, "20240729000001GEN")
        self.assertEqual(second.name, "20240729000002GEN")

    def test_refund_starting_sequence_has_r_prefix(self):
        self._enable_custom_sequence()
        refund = self.env["account.move"].new({
            "move_type": "in_refund",
            "journal_id": self.company_data["default_journal_purchase"].id,
            "date": fields.Date.to_date("2024-07-18"),
        })
        self.assertEqual(refund._get_starting_sequence(), "R20240718000000PUR")

    def test_account_manager_can_enable_date_number_type_sequence(self):
        settings = self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global"
        ).with_user(self.simple_accountman)
        settings.write({
            "kr_move_sequence_rule": "date_number_type",
        })
        settings.action_save()
        self.assertEqual(
            self.company_data["company"].kr_move_sequence_rule,
            "date_number_type",
        )

        move = self._create_entry("2024-07-22")
        move.action_post()
        self.assertEqual(move.name, "20240722000001GEN")

    def test_legacy_settings_fields_remain_safe_during_module_upgrade(self):
        settings_model = self.env["account.kr.plus.settings"]
        self.assertFalse(
            settings_model._fields["kr_use_custom_move_sequence"].store
        )
        self.assertFalse(settings_model._fields["kr_move_sequence_format"].store)

        settings = self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global"
        ).with_user(self.simple_accountman)
        settings.write({
            "kr_use_custom_move_sequence": True,
            "kr_move_sequence_format": "date_number",
        })
        settings.action_save()

        self.assertEqual(settings.kr_move_sequence_rule, "date_number")
        self.assertEqual(
            self.company_data["company"].kr_move_sequence_rule,
            "date_number",
        )

    def test_former_legacy_sequence_key_maps_to_current_rule(self):
        settings = self.env.ref(
            "account_kr_plus_patch.account_kr_plus_settings_global"
        ).with_user(self.simple_accountman)
        settings.write({
            "kr_use_custom_move_sequence": True,
            "kr_move_sequence_format": "legacy",
        })

        self.assertEqual(settings.kr_move_sequence_rule, "date_number_type")

    def test_regular_accountant_cannot_change_sequence_settings(self):
        accountant = new_test_user(
            self.env,
            login="kr_plus_regular_accountant",
            groups="account.group_account_user",
        )
        with self.assertRaises(AccessError):
            self.env.ref(
                "account_kr_plus_patch.account_kr_plus_settings_global"
            ).with_user(accountant).write({
                "kr_move_sequence_rule": "date_number_type",
            })

    def test_historical_sequence_survives_rule_change(self):
        self._enable_custom_sequence()
        typed_move = self._create_entry("2024-07-23")
        typed_move.action_post()
        self.assertEqual(typed_move.name, "20240723000001GEN")

        self._enable_custom_sequence("date_number")
        self.assertTrue(typed_move._sequence_matches_date())
        _where, params = typed_move._get_last_sequence_domain()
        self.assertEqual(params["company_id"], self.company_data["company"].id)
        self.assertNotIn("journal_id", params)
        self.assertNotIn("sequence_suffix", params)

        plain_move = self._create_entry("2024-07-23")
        plain_move.action_post()
        self.assertEqual(plain_move.name, "20240723000002")

    def test_type_code_rejects_more_than_three_characters(self):
        with self.assertRaises(ValidationError):
            self.misc_journal.kr_sequence_code = "GENERAL01"

    def test_sequence_repair_previews_before_applying_and_only_renames(self):
        move = self._create_entry("2024-07-24")
        move.action_post()
        original_name = move.name
        self.assertNotEqual(original_name, "20240724000001GEN")

        self._enable_custom_sequence()
        wizard = self.env[
            "account.kr.move.sequence.repair.wizard"
        ].with_user(self.simple_accountman).create({
            "company_id": self.company_data["company"].id,
            "date_from": fields.Date.to_date("2024-07-24"),
            "date_to": fields.Date.to_date("2024-07-24"),
            "journal_ids": [Command.set(self.misc_journal.ids)],
        })
        wizard.action_scan()
        line = wizard.line_ids.filtered(lambda item: item.move_id == move)

        self.assertEqual(wizard.state, "preview")
        self.assertEqual(len(line), 1)
        self.assertEqual(line.current_name, original_name)
        self.assertEqual(line.proposed_name, "20240724000001GEN")
        self.assertEqual(move.name, original_name)

        unchanged_fields = [
            "date", "journal_id", "state", "amount_total", "line_ids",
            "payment_reference", "is_manually_modified", "made_sequence_gap",
        ]
        before = move.read(unchanged_fields)[0]
        wizard.action_apply()
        after = move.read(unchanged_fields)[0]

        self.assertEqual(move.name, "20240724000001GEN")
        self.assertEqual(before, after)
        self.assertEqual(line.result_state, "applied")

    def test_sequence_repair_does_not_interfere_with_odoo_default(self):
        wizard = self.env[
            "account.kr.move.sequence.repair.wizard"
        ].with_user(self.simple_accountman).create({
            "company_id": self.company_data["company"].id,
            "date_from": fields.Date.to_date("2024-07-01"),
            "date_to": fields.Date.to_date("2024-07-31"),
        })
        with self.assertRaisesRegex(UserError, "Odoo 기본"):
            wizard.action_scan()

    def test_sequence_repair_defaults_to_all_journals_and_manual_drafts_only(self):
        archived_journal = self.env["account.journal"].create({
            "name": "보관 저널 소급 테스트",
            "code": "KRA",
            "type": "general",
            "company_id": self.company_data["company"].id,
            "active": False,
            "kr_sequence_code": "ARC",
        })
        manual_draft = self._create_entry("2024-07-31")
        manual_draft.with_context(skip_is_manually_modified=True).write({
            "name": "DIRECT-DRAFT",
        })
        unnamed_draft = self._create_entry("2024-07-31")
        self._enable_custom_sequence("date_number")

        wizard = self.env[
            "account.kr.move.sequence.repair.wizard"
        ].with_user(self.simple_accountman).with_context(
            default_company_id=self.company_data["company"].id
        ).create({
            "company_id": self.company_data["company"].id,
            "date_from": fields.Date.to_date("2024-07-31"),
            "date_to": fields.Date.to_date("2024-07-31"),
            "include_draft": True,
        })

        all_journals = self.env["account.journal"].with_context(
            active_test=False
        ).search([
            ("company_id", "=", self.company_data["company"].id),
        ])
        target_moves = self.env["account.move"].search(
            wizard._get_move_domain()
        )
        self.assertEqual(set(wizard.journal_ids.ids), set(all_journals.ids))
        self.assertIn(archived_journal, wizard.journal_ids)
        self.assertIn(manual_draft, target_moves)
        self.assertNotIn(unnamed_draft, target_moves)
        self.assertIn(("state", "=", "draft"), wizard._get_move_domain())
        self.assertNotIn(("state", "=", "cancel"), wizard._get_move_domain())

    def test_sequence_repair_proposals_share_number_across_ttt_codes(self):
        general_move = self._create_entry("2024-07-27")
        sale_code_move = self._create_entry(
            "2024-07-27", journal=self.other_misc_journal
        )
        general_move.action_post()
        sale_code_move.action_post()
        self._enable_custom_sequence()

        wizard = self.env[
            "account.kr.move.sequence.repair.wizard"
        ].with_user(self.simple_accountman).create({
            "company_id": self.company_data["company"].id,
            "date_from": fields.Date.to_date("2024-07-27"),
            "date_to": fields.Date.to_date("2024-07-27"),
            "journal_ids": [Command.set(
                (self.misc_journal | self.other_misc_journal).ids
            )],
        })
        wizard.action_scan()

        general_line = wizard.line_ids.filtered(
            lambda item: item.move_id == general_move
        )
        sale_code_line = wizard.line_ids.filtered(
            lambda item: item.move_id == sale_code_move
        )
        self.assertEqual(general_line.proposed_name, "20240727000001GEN")
        self.assertEqual(sale_code_line.proposed_name, "20240727000002SAL")

    def test_sequence_repair_finds_existing_cross_ttt_duplicate(self):
        general_move = self._create_entry("2024-07-28")
        sale_code_move = self._create_entry(
            "2024-07-28", journal=self.other_misc_journal
        )
        general_move.action_post()
        sale_code_move.action_post()
        general_move.name = "20240728000001GEN"
        sale_code_move.name = "20240728000001SAL"
        self._enable_custom_sequence()

        wizard = self.env[
            "account.kr.move.sequence.repair.wizard"
        ].with_user(self.simple_accountman).create({
            "company_id": self.company_data["company"].id,
            "date_from": fields.Date.to_date("2024-07-28"),
            "date_to": fields.Date.to_date("2024-07-28"),
            "journal_ids": [Command.set(
                (self.misc_journal | self.other_misc_journal).ids
            )],
        })
        wizard.action_scan()

        duplicate_line = wizard.line_ids.filtered(
            lambda item: item.move_id == sale_code_move
        )
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(duplicate_line.issue_type, "duplicate_sequence")
        self.assertEqual(duplicate_line.proposed_name, "20240728000002SAL")
        self.assertEqual(sale_code_move.name, "20240728000001SAL")

    def test_sequence_repair_identifies_orphaned_number(self):
        move = self._create_entry("2024-07-25")
        move.action_post()
        move.name = "ORPHAN"
        self._enable_custom_sequence("date_number")

        wizard = self.env[
            "account.kr.move.sequence.repair.wizard"
        ].with_user(self.simple_accountman).create({
            "company_id": self.company_data["company"].id,
            "date_from": fields.Date.to_date("2024-07-25"),
            "date_to": fields.Date.to_date("2024-07-25"),
            "journal_ids": [Command.set(self.misc_journal.ids)],
        })
        wizard.action_scan()
        line = wizard.line_ids.filtered(lambda item: item.move_id == move)

        self.assertEqual(line.issue_type, "orphaned")
        self.assertEqual(line.proposed_name, "20240725000001")
        self.assertEqual(move.name, "ORPHAN")

    def test_bank_journal_is_selected_when_mapping_is_unique(self):
        liquidity_account = self.env["account.account"].create({
            "name": "테스트 당좌예금",
            "code": "KRPLUS101",
            "account_type": "asset_cash",
            "company_ids": [Command.set(self.company_data["company"].ids)],
        })
        bank_journal = self.env["account.journal"].create({
            "name": "테스트은행 당좌예금",
            "code": "KB1",
            "type": "bank",
            "company_id": self.company_data["company"].id,
            "default_account_id": liquidity_account.id,
            "kr_sequence_code": "BNK",
        })

        move = self._create_entry("2024-07-20", debit_account=liquidity_account)
        bank_line = move.line_ids.filtered(
            lambda line: line.account_id == liquidity_account
        )
        self.assertEqual(bank_line.kr_bank_journal_id, bank_journal)
        self.assertEqual(move.kr_bank_journal_ids, bank_journal)

        non_bank_move = self._create_entry("2024-07-20")
        self.assertFalse(non_bank_move.kr_bank_journal_ids)

    def test_bank_account_setup_creates_default_account_and_chatter_guide(self):
        bank_journal = self.env["account.journal"].with_context(
            kr_bank_account_setup=True
        ).create({
            "name": "안내 테스트은행 운영계좌",
            "code": "KBG",
            "company_id": self.company_data["company"].id,
        })

        self.assertEqual(bank_journal.type, "bank")
        self.assertTrue(bank_journal.default_account_id)
        self.assertEqual(
            bank_journal.default_account_id.account_type,
            "asset_cash",
        )
        self.assertIn("당좌예금", bank_journal.default_account_id.name)

        guide_messages = bank_journal.message_ids.filtered(
            lambda message: "계좌 설정을 만들었어요" in (message.body or "")
        )
        self.assertEqual(len(guide_messages), 1)
        self.assertIn(
            bank_journal.default_account_id.display_name,
            guide_messages.body,
        )
        self.assertIn("계좌번호", guide_messages.body)
        self.assertIn("전표유형 코드", guide_messages.body)

    def test_ambiguous_bank_mapping_requires_selection(self):
        liquidity_account = self.env["account.account"].create({
            "name": "공용 당좌예금",
            "code": "KRPLUS102",
            "account_type": "asset_cash",
            "company_ids": [Command.set(self.company_data["company"].ids)],
        })
        banks = self.env["account.journal"].create([
            {
                "name": "A은행 당좌",
                "code": "KA1",
                "type": "bank",
                "company_id": self.company_data["company"].id,
                "default_account_id": liquidity_account.id,
                "kr_sequence_code": "BNK",
            },
            {
                "name": "B은행 당좌",
                "code": "KB2",
                "type": "bank",
                "company_id": self.company_data["company"].id,
                "default_account_id": liquidity_account.id,
                "kr_sequence_code": "BNK",
            },
        ])
        move = self._create_entry("2024-07-21", debit_account=liquidity_account)
        bank_line = move.line_ids.filtered(
            lambda line: line.account_id == liquidity_account
        )

        self.assertFalse(bank_line.kr_bank_journal_id)
        with self.assertRaisesRegex(UserError, "연결 은행계좌"):
            move.action_post()

        bank_line.kr_bank_journal_id = banks[0]
        move.action_post()
        self.assertEqual(bank_line.kr_bank_journal_id, banks[0])
