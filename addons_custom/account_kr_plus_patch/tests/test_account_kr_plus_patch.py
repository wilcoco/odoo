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

    def _create_entry(self, move_date, debit_account=None, bank_journal=None):
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
            "journal_id": self.misc_journal.id,
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

    def test_daily_compact_sequence(self):
        first = self._create_entry("2024-07-18")
        second = self._create_entry("2024-07-18")
        next_day = self._create_entry("2024-07-19")

        first.action_post()
        second.action_post()
        next_day.action_post()

        self.assertEqual(first.name, "20240718000001GEN")
        self.assertEqual(second.name, "20240718000002GEN")
        self.assertEqual(next_day.name, "20240719000001GEN")

    def test_refund_starting_sequence_has_r_prefix(self):
        refund = self.env["account.move"].new({
            "move_type": "in_refund",
            "journal_id": self.company_data["default_journal_purchase"].id,
            "date": fields.Date.to_date("2024-07-18"),
        })
        self.assertEqual(refund._get_starting_sequence(), "R20240718000000PUR")

    def test_account_manager_can_enable_extended_sequence(self):
        settings = self.env["account.kr.plus.settings"].with_user(
            self.simple_accountman
        ).create({
            "company_id": self.company_data["company"].id,
            "kr_move_sequence_format": "extended",
        })
        settings.action_save()
        self.assertEqual(
            self.company_data["company"].kr_move_sequence_format,
            "extended",
        )

        self.misc_journal.kr_sequence_code = "GENERAL01"
        move = self._create_entry("2024-07-22")
        move.action_post()
        self.assertEqual(move.name, "20240722000001-GENERAL01")

    def test_regular_accountant_cannot_change_sequence_settings(self):
        accountant = new_test_user(
            self.env,
            login="kr_plus_regular_accountant",
            groups="account.group_account_user",
        )
        with self.assertRaises(AccessError):
            self.env["account.kr.plus.settings"].with_user(accountant).create({
                "company_id": self.company_data["company"].id,
                "kr_move_sequence_format": "extended",
            })

    def test_historical_sequence_survives_format_and_code_change(self):
        legacy_move = self._create_entry("2024-07-23")
        legacy_move.action_post()
        self.assertEqual(legacy_move.name, "20240723000001GEN")

        self.company_data["company"].kr_move_sequence_format = "extended"
        self.misc_journal.kr_sequence_code = "GENERAL01"
        self.assertTrue(legacy_move._sequence_matches_date())
        _where, params = legacy_move._get_last_sequence_domain()
        self.assertEqual(params["sequence_suffix"], "GEN")

        extended_move = self._create_entry("2024-07-23")
        extended_move.action_post()
        self.assertEqual(extended_move.name, "20240723000001-GENERAL01")

    def test_legacy_format_rejects_extended_code(self):
        with self.assertRaises(ValidationError):
            self.misc_journal.kr_sequence_code = "GENERAL01"

    def test_cannot_restore_legacy_format_with_extended_codes(self):
        self.company_data["company"].kr_move_sequence_format = "extended"
        self.misc_journal.kr_sequence_code = "GENERAL01"
        with self.assertRaises(ValidationError):
            self.company_data["company"].kr_move_sequence_format = "legacy"

    def test_bank_journal_is_selected_when_mapping_is_unique(self):
        liquidity_account = self.env["account.account"].create({
            "name": "테스트 보통예금",
            "code": "KRPLUS101",
            "account_type": "asset_cash",
            "company_ids": [Command.set(self.company_data["company"].ids)],
        })
        bank_journal = self.env["account.journal"].create({
            "name": "테스트은행 보통예금",
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
