from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestManualFlag(AccountTestInvoicingCommon):
    """수기 표시는 화면 저장(web_save)에만 남고, 프로그램 write에는 남지 않는다."""

    def _bill_vals(self, **values):
        vals = {
            "move_type": "in_invoice",
            "partner_id": self.partner_a.id,
            "journal_id": self.company_data["default_journal_purchase"].id,
            "invoice_line_ids": [Command.create({
                "name": "수기 테스트", "quantity": 1, "price_unit": 1000,
            })],
        }
        vals.update(values)
        return vals

    def test_programmatic_create_and_write_do_not_flag(self):
        bill = self.env["account.move"].create(self._bill_vals(ref="20260901-AAAAAAAA-BBBBBBBB"))
        self.assertFalse(bill.is_manually_modified)
        bill.write({"narration": "스크립트가 채운 값"})
        bill.write({"kr_doc_type": "tax_invoice"})
        self.assertFalse(bill.is_manually_modified)
        bill.action_post()
        self.assertFalse(bill.is_manually_modified)

    def test_new_form_defaults_to_manual_checked(self):
        # 화면 신규 등록 폼은 '수기'가 체크된 상태로 열린다
        defaults = self.env["account.move"].default_get(["is_manually_modified"])
        self.assertTrue(defaults.get("is_manually_modified"))

    def test_business_logic_created_move_is_not_flagged(self):
        # 오두 업무 로직(역분개)이 만든 전표는 수기가 아니다
        bill = self.env["account.move"].create(self._bill_vals())
        bill.action_post()
        reversal = bill._reverse_moves([{"date": bill.date}])
        self.assertFalse(reversal.is_manually_modified)
        self.assertFalse(bill.is_manually_modified)

    def test_web_save_flags_existing_and_new(self):
        bill = self.env["account.move"].create(self._bill_vals())
        bill.web_save({"narration": "사람이 고침"}, {"id": {}})
        self.assertTrue(bill.is_manually_modified)
        result = self.env["account.move"].web_save(self._bill_vals(), {"id": {}})
        created = self.env["account.move"].browse(result[0]["id"])
        self.assertTrue(created.is_manually_modified)

    def test_wizard_clears_and_sets_with_confirmation_flow(self):
        bill = self.env["account.move"].create(self._bill_vals())
        bill.web_save({"narration": "사람이 고침"}, {"id": {}})
        wizard = self.env["account.kr.manual.flag.wizard"].with_context(
            active_model="account.move", active_ids=bill.ids).create({})
        self.assertEqual(wizard.move_ids, bill)
        self.assertEqual(wizard.change_count, 1)
        wizard.action_apply()
        self.assertFalse(bill.is_manually_modified)
        wizard2 = self.env["account.kr.manual.flag.wizard"].create({
            "move_ids": [Command.set(bill.ids)], "action": "set"})
        wizard2.action_apply()
        self.assertTrue(bill.is_manually_modified)
