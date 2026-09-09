from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from ..tools.approval_number import approval_number_key, normalize_approval_number


@tagged("post_install", "-at_install")
class TestApprovalNumberContract(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "승인번호 계약 테스트 거래처",
        })

    def _bill(self, **values):
        vals = {
            "move_type": "in_invoice",
            "invoice_date": fields.Date.today(),
            "partner_id": self.partner.id,
            "journal_id": self.company_data["default_journal_purchase"].id,
        }
        vals.update(values)
        return self.env["account.move"].create(vals)

    def test_normalized_key_and_public_lookup_ignore_format(self):
        expected = "20260831-ABCDEFGH-12345678"
        bill = self._bill(kr_approval_number="20260831abcdefgh12345678")

        self.assertEqual(normalize_approval_number(bill.kr_approval_number), expected)
        self.assertEqual(approval_number_key(bill.kr_approval_number), expected)
        self.assertEqual(bill.kr_approval_number_key, expected)
        self.assertEqual(
            self.env["account.move"]._kr_find_by_approval_number(
                "20260831 - abcdefgh - 12345678", limit=1
            ),
            bill,
        )

    def test_logical_duplicate_is_blocked(self):
        self._bill(kr_approval_number="20260830-AAAAAAAA-BBBBBBBB")
        with self.assertRaises(ValidationError):
            self._bill(kr_approval_number="20260830aaaaaaaaBBBBBBBB")

    def test_ref_only_fills_empty_canonical_and_ref_is_preserved(self):
        bill = self._bill(ref="20260829ccccccccdddddddd")
        self.assertEqual(bill.ref, "20260829ccccccccdddddddd")
        self.assertEqual(
            bill.kr_approval_number, "20260829-CCCCCCCC-DDDDDDDD"
        )
        bill.ref = "20260829-EEEEEEEE-FFFFFFFF"
        self.assertEqual(
            bill.kr_approval_number, "20260829-CCCCCCCC-DDDDDDDD"
        )

    def _invoice(self, **values):
        vals = {
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "journal_id": self.company_data["default_journal_sale"].id,
        }
        vals.update(values)
        return self.env["account.move"].create(vals)

    def test_sales_ref_also_fills_empty_canonical(self):
        # 이관처럼 매출 청구서 ref에 24자리 승인번호가 들어오면 정본에도 복사된다
        invoice = self._invoice(ref="20260901aaaaaaaabbbbbbbb")
        self.assertEqual(invoice.kr_approval_number, "20260901-AAAAAAAA-BBBBBBBB")
        self.assertEqual(invoice.ref, "20260901aaaaaaaabbbbbbbb")
        # 고객 참조번호 등 형식이 다른 ref는 건드리지 않는다
        plain = self._invoice(ref="PO-2026-0001")
        self.assertFalse(plain.kr_approval_number)
        # 이미 정본이 있으면 ref로 덮어쓰지 않는다
        invoice.ref = "20260902-CCCCCCCC-DDDDDDDD"
        self.assertEqual(invoice.kr_approval_number, "20260901-AAAAAAAA-BBBBBBBB")

    def test_merge_wizard_reference_scan_ignores_its_own_views(self):
        Wizard = self.env["kr.approval.number.merge"]
        View = self.env["ir.ui.view"]
        View.create({
            "name": "self reference (must be ignored)", "model": Wizard._name,
            "type": "form", "arch": "<form><div>x_escon_tax_approval_no</div></form>",
        })
        details = dict(Wizard._studio_reference_status()["details"])
        self.assertNotIn("화면", details)
        View.create({
            "name": "real reference (must be counted)", "model": "account.move",
            "type": "form", "arch": "<form><div>x_escon_tax_approval_no</div></form>",
        })
        details = dict(Wizard._studio_reference_status()["details"])
        self.assertEqual(details.get("화면"), 1)

    def test_approval_number_cannot_be_cleared_or_changed_after_posting(self):
        bill = self._bill(
            kr_approval_number="20260828-11111111-AAAAAAAA",
            invoice_line_ids=[Command.create({
                "name": "승인번호 보호",
                "quantity": 1,
                "price_unit": 1000,
            })],
        )
        with self.assertRaises(UserError):
            bill.kr_approval_number = False

        bill.action_post()
        with self.assertRaises(UserError):
            bill.kr_approval_number = "20260828-22222222-BBBBBBBB"

    def test_account_manager_pumui_access_is_separate(self):
        # 회계 관리자만으로 품의서 생성 권한까지 있다고 가정하지 않는다.
        manager = self.simple_accountman
        self.assertTrue(manager.has_group("account.group_account_manager"))
        self.assertFalse(manager.has_group("pumui_approval.group_pumui_user"))
        self.assertFalse(self.env["ir.model.access"].with_user(manager).check(
            "pumui.request", "create", raise_exception=False,
        ))

    def test_pumui_exposes_linked_canonical_numbers(self):
        # 실제 ACL을 적용하는 회계+품의서 관리자. 업무 호출에 sudo를 쓰지 않는다.
        self.assertFalse(self.env.su)
        self.assertTrue(self.env.user.has_group("account.group_account_manager"))
        self.env.user.sudo().write({"groups_id": [Command.link(
            self.env.ref("pumui_approval.group_pumui_manager").id,
        )]})
        self.assertTrue(self.env.user.has_group("pumui_approval.group_pumui_manager"))
        request = self.env["pumui.request"].create({
            "title": "승인번호 연동 품의",
            "partner_id": self.partner.id,
        })
        self._bill(
            pumui_id=request.id,
            kr_approval_number="20260827abcdefgh12345678",
            kr_origin_number="20260826zzzzzzzz99999999",
        )
        self.assertEqual(
            request.kr_approval_numbers, "20260827-ABCDEFGH-12345678"
        )
        self.assertEqual(
            request.kr_origin_numbers, "20260826-ZZZZZZZZ-99999999"
        )

    def test_checklist_detects_origin_without_matching_original(self):
        refund = self.env["account.move"].create({
            "move_type": "in_refund",
            "partner_id": self.partner.id,
            "journal_id": self.company_data["default_journal_purchase"].id,
            "kr_approval_number": "20260825-AAAAAAAA-BBBBBBBB",
            "kr_origin_number": "20260824-CCCCCCCC-DDDDDDDD",
        })
        checklist = self.env["kr.close.checklist"].create({})

        self.assertIn(refund.id, checklist._kr_unmatched_origin_move_ids())
        self.assertGreaterEqual(checklist.correction_origin_unmatched, 1)

    def test_missing_studio_field_is_never_auto_removed(self):
        wizard = self.env["kr.approval.number.merge"].create({})
        self.assertFalse(wizard.studio_field_present)
        self.assertFalse(wizard.studio_retirement_ready)
        wizard.action_run()
        self.assertIn("제거할 필드 없음", wizard.result)
