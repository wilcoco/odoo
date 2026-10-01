from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestKrNcAsset(AccountTestInvoicingCommon):
    """비유동자산 한국식 확장 — 비상각 자산과 자산별 계정과목."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.misc_journal = cls.company_data["default_journal_misc"]
        Account = cls.env["account.account"]
        cls.land_base = Account.create(
            {
                "code": "800003",
                "name": "토지",
                "account_type": "asset_fixed",
                "company_ids": [Command.link(cls.env.company.id)],
            }
        )
        cls.down_base = Account.create(
            {
                "code": "803001",
                "name": "토지 계약금",
                "account_type": "asset_current",
                "company_ids": [Command.link(cls.env.company.id)],
            }
        )
        cls.interim_base = Account.create(
            {
                "code": "803002",
                "name": "토지 중도금",
                "account_type": "asset_current",
                "company_ids": [Command.link(cls.env.company.id)],
            }
        )
        cls.balance_base = Account.create(
            {
                "code": "803003",
                "name": "토지 잔금",
                "account_type": "asset_current",
                "company_ids": [Command.link(cls.env.company.id)],
            }
        )
        cls.env.company.write(
            {
                "kr_land_base_account_id": cls.land_base.id,
                "kr_land_down_account_id": cls.down_base.id,
                "kr_land_interim_account_id": cls.interim_base.id,
                "kr_land_balance_account_id": cls.balance_base.id,
                "kr_asset_reclass_journal_id": cls.misc_journal.id,
            }
        )

    def _make_land(self, name, value, **kwargs):
        values = {
            "name": name,
            "acquisition_date": fields.Date.from_string("2025-04-30"),
            "prorata_date": fields.Date.from_string("2025-04-30"),
            "prorata_computation_type": "none",
            "original_value": value,
            "account_asset_id": self.land_base.id,
            "account_depreciation_id": self.land_base.id,
            "account_depreciation_expense_id": self.company_data["default_account_expense"].id,
            "journal_id": self.misc_journal.id,
            "method": "linear",
            "method_number": 1,
            "method_period": "12",
            "kr_non_depreciable": True,
        }
        values.update(kwargs)
        return self.env["account.asset"].create(values)

    def test_non_depreciable_asset_has_no_depreciation(self):
        """비상각 자산은 감가상각 제외금액이 취득원가와 같고 상각 전표가 생기지 않는다."""
        asset = self._make_land("완주농공단지 E-2 토지", 1000000)
        self.assertEqual(asset.salvage_value, asset.original_value)
        self.assertEqual(asset.value_residual, 0)
        asset.validate()
        self.assertEqual(asset.state, "open")
        self.assertFalse(asset.depreciation_move_ids)

    def test_non_depreciable_follows_original_value(self):
        """취득원가를 바꾸면 감가상각 제외금액도 같이 따라간다."""
        asset = self._make_land("완주농공단지 E-9 토지", 1000000)
        asset.original_value = 1500000
        self.assertEqual(asset.salvage_value, 1500000)

    def test_create_asset_accounts_by_code_suffix(self):
        """기준 계정 코드 뒤에 일련번호를 붙인 자산별 계정이 만들어지고 유형을 물려받는다."""
        asset = self._make_land("완주농공단지 E-11 토지", 1000000)
        asset.action_kr_create_accounts()
        kinds = {line.kind: line.account_id for line in asset.kr_account_ids}
        self.assertEqual(set(kinds), {"asset", "down_payment", "interim_payment", "balance_payment"})
        self.assertEqual(kinds["asset"].code, "%s%d" % (self.land_base.code, asset.kr_asset_no))
        self.assertEqual(kinds["down_payment"].code, "%s%d" % (self.down_base.code, asset.kr_asset_no))
        # 회계 통계에서 같은 성격으로 잡히도록 계정 유형을 물려받는다
        self.assertEqual(kinds["asset"].account_type, self.land_base.account_type)
        self.assertEqual(kinds["down_payment"].account_type, self.down_base.account_type)
        # 취득원가 계정은 자산에 연결된다
        self.assertEqual(asset.account_asset_id, kinds["asset"])

    def test_create_asset_accounts_is_idempotent(self):
        """두 번 실행해도 계정이 중복되지 않는다."""
        asset = self._make_land("토지 A", 1000000)
        asset.action_kr_create_accounts()
        count = len(asset.kr_account_ids)
        accounts = asset.kr_account_ids.account_id
        asset.action_kr_create_accounts()
        self.assertEqual(len(asset.kr_account_ids), count)
        self.assertEqual(asset.kr_account_ids.account_id, accounts)

    def test_asset_numbers_do_not_collide(self):
        """자산이 여러 건이면 일련번호가 1, 2, 3… 으로 매겨진다."""
        first = self._make_land("토지 1", 1000000)
        second = self._make_land("토지 2", 2000000)
        first.action_kr_create_asset_account()
        second.action_kr_create_asset_account()
        self.assertNotEqual(first.kr_asset_no, second.kr_asset_no)
        self.assertNotEqual(first.account_asset_id, second.account_asset_id)

    def test_reclass_wizard_creates_draft_move_only(self):
        """재분류 마법사는 초안 전표만 만들고 전기하지 않는다."""
        asset = self._make_land("토지 B", 1000000)
        asset.action_kr_create_asset_account()
        wizard = self.env["account.asset.kr.reclass.wizard"].create(
            {
                "asset_ids": [Command.set(asset.ids)],
                "journal_id": self.misc_journal.id,
                "date": fields.Date.context_today(self.env.user),
                "source_account_id": self.land_base.id,
            }
        )
        action = wizard.action_create_draft_move()
        move = self.env["account.move"].browse(action["res_id"])
        self.assertEqual(move.state, "draft")
        self.assertEqual(sum(move.line_ids.mapped("debit")), 1000000)
        self.assertEqual(sum(move.line_ids.mapped("credit")), 1000000)
        self.assertIn(asset.account_asset_id, move.line_ids.account_id)

    def test_reclass_requires_asset_account(self):
        """자산별 계정이 없으면 재분류를 막는다."""
        asset = self._make_land("토지 C", 1000000)
        wizard = self.env["account.asset.kr.reclass.wizard"].create(
            {
                "asset_ids": [Command.set(asset.ids)],
                "journal_id": self.misc_journal.id,
                "date": fields.Date.context_today(self.env.user),
                "source_account_id": self.land_base.id,
            }
        )
        with self.assertRaises(UserError):
            wizard.action_create_draft_move()
