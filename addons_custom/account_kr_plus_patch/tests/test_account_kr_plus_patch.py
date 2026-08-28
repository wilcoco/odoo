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
        self.company_data["company"].write({
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

    def test_journal_entry_action_and_vendor_list_show_requested_fields(self):
        action = self.env.ref(
            "account_kr_plus_patch.action_kr_journal_entries"
        )
        self.assertEqual(action.domain, "[]")

        arch = self.env.ref(
            "account_kr_plus_patch.view_kr_vendor_tax_invoice_list"
        ).arch_db
        self.assertIn('name="status_in_payment"', arch)
        self.assertIn('name="kr_doc_type"', arch)
        self.assertIn('name="kr_tax_type"', arch)
        self.assertIn('string="미납금액"', arch)
        self.assertIn('string="결제완료 금액"', arch)

        settings_arch = self.env.ref(
            "account_kr_plus_patch.view_account_kr_plus_settings_form"
        ).arch_db
        self.assertIn('string="전표 설정"', settings_arch)
        self.assertIn('string="전표유형 및 코드 설정"', settings_arch)
        self.assertIn('string="전표번호 점검 및 수정"', settings_arch)
        self.assertIn('string="계좌 설정"', settings_arch)

    def test_unlinked_approval_status_is_not_blank(self):
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

    def test_daily_date_number_sequence_without_type_code(self):
        self._enable_custom_sequence("date_number")
        move = self._create_entry("2024-07-18")
        move.action_post()

        self.assertEqual(move.name, "20240718000001")

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
        settings = self.env["account.kr.plus.settings"].with_user(
            self.simple_accountman
        ).create({
            "company_id": self.company_data["company"].id,
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

    def test_regular_accountant_cannot_change_sequence_settings(self):
        accountant = new_test_user(
            self.env,
            login="kr_plus_regular_accountant",
            groups="account.group_account_user",
        )
        with self.assertRaises(AccessError):
            self.env["account.kr.plus.settings"].with_user(accountant).create({
                "company_id": self.company_data["company"].id,
                "kr_move_sequence_rule": "date_number_type",
            })

    def test_historical_sequence_survives_rule_change(self):
        self._enable_custom_sequence()
        typed_move = self._create_entry("2024-07-23")
        typed_move.action_post()
        self.assertEqual(typed_move.name, "20240723000001GEN")

        self.company_data["company"].kr_move_sequence_rule = "date_number"
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
