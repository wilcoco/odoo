from lxml import etree

from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.account_kr_reports.wizard.approval_number_merge import STUDIO_FIELD
from odoo.tests import Form, tagged
from odoo.tools.safe_eval import safe_eval

FORM_VIEW = "account_kr_plus_patch.view_move_form_kr_plus"
REFUND_TYPES = ("out_refund", "in_refund")
DUE_LABELS = {
    "out_invoice": "수금기한",
    "out_refund": "환불기한",
    "in_invoice": "입금기한",
    "in_refund": "환불기한",
}


def _date(value):
    return fields.Date.to_date(value)


class InvoiceDueCopyCommon(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 결제조건이 없는 국내 거래처(회사 실데이터와 같은 조건)
        cls.partner_kr = cls.env["res.partner"].create({"name": "국내 거래처"})
        cls.term_30 = cls.env.ref("account.account_payment_term_30days")

    @staticmethod
    def _approval(serial, suffix):
        return "20260901-%08d-%s" % (serial, suffix * 8)

    def _invoice_vals(self, move_type, serial, **values):
        tax = (
            self.company_data["default_tax_sale"]
            if move_type.startswith("out_")
            else self.company_data["default_tax_purchase"]
        )
        vals = {
            "move_type": move_type,
            "partner_id": self.partner_kr.id,
            "invoice_date": _date("2026-09-01"),
            "kr_approval_number": self._approval(serial, "A"),
            "invoice_line_ids": [Command.create({
                "name": "복제 원본 품목",
                "quantity": 1,
                "price_unit": 1000.0,
                "tax_ids": [Command.set(tax.ids)],
            })],
        }
        if move_type in REFUND_TYPES:
            vals["kr_origin_number"] = self._approval(serial, "Z")
        vals.update(values)
        return vals


@tagged("post_install", "-at_install")
class TestInvoiceDueDateForm(InvoiceDueCopyCommon):
    """전표 폼에서 수금·지급기한을 보고 고칠 수 있다."""

    def test_form_shows_due_date_label_by_move_type(self):
        arch = etree.fromstring(
            self.env["account.move"].get_view(
                self.env.ref(FORM_VIEW).id, "form"
            )["arch"]
        )
        labels = arch.xpath("//label[@for='invoice_date_due']")
        self.assertEqual(len(labels), 3)
        for move_type, expected in DUE_LABELS.items():
            with self.subTest(move_type=move_type):
                visible = [
                    label.get("string")
                    for label in labels
                    if not safe_eval(label.get("invisible"), {"move_type": move_type})
                ]
                self.assertEqual(visible, [expected])

        # 기한은 전표일자 바로 아래에 있고, 일반 전표에서는 숨긴다.
        group = arch.xpath("//field[@name='invoice_date']/..")[0]
        names = [
            node.get("name") or node.get("class")
            for node in group
            if node.tag in ("field", "div")
        ]
        self.assertEqual(
            names[names.index("invoice_date"):names.index("partner_id")],
            [
                "invoice_date", "date", "o_td_label",
                "invoice_date_due", "invoice_payment_term_id",
            ],
        )
        for node in group.xpath(
            "div[@class='o_td_label'] | field[@name='invoice_date_due'] "
            "| field[@name='invoice_payment_term_id']"
        ):
            self.assertTrue(safe_eval(node.get("invisible"), {"move_type": "entry"}))

    def test_form_always_shows_approval_number_for_tax_documents(self):
        # 목록에서는 기본 숨김이지만, 폼에서는 신규·전기·증빙유형과 무관하게 보인다.
        for serial, move_type in enumerate(DUE_LABELS, start=31):
            with self.subTest(move_type=move_type, state="new"):
                move_form = Form(
                    self.env["account.move"].with_context(default_move_type=move_type),
                    view=FORM_VIEW,
                )
                self.assertFalse(
                    move_form._get_modifier("kr_approval_number", "invisible")
                )
                self.assertFalse(
                    move_form._get_modifier("kr_approval_number", "readonly")
                )
            with self.subTest(move_type=move_type, state="posted"):
                move = self.env["account.move"].create(self._invoice_vals(
                    move_type, serial, kr_doc_type="cash_receipt",
                ))
                move.action_post()
                move_form = Form(move, view=FORM_VIEW)
                self.assertFalse(
                    move_form._get_modifier("kr_approval_number", "invisible")
                )

        entry_form = Form(
            self.env["account.move"].with_context(default_move_type="entry"),
            view=FORM_VIEW,
        )
        self.assertTrue(entry_form._get_modifier("kr_approval_number", "invisible"))

    def test_due_date_is_editable_until_payment_term_is_selected(self):
        with Form(
            self.env["account.move"].with_context(default_move_type="in_invoice"),
            view=FORM_VIEW,
        ) as move_form:
            move_form.partner_id = self.partner_kr
            move_form.invoice_date = _date("2026-09-01")
            with move_form.invoice_line_ids.new() as line_form:
                line_form.name = "기한 입력"
                line_form.price_unit = 1000.0
            self.assertFalse(move_form._get_modifier("invoice_date_due", "readonly"))
            move_form.invoice_date_due = _date("2026-09-25")
        bill = move_form.record
        self.assertEqual(bill.invoice_date_due, _date("2026-09-25"))

        with Form(bill, view=FORM_VIEW) as move_form:
            move_form.invoice_payment_term_id = self.term_30
            self.assertTrue(move_form._get_modifier("invoice_date_due", "readonly"))
        self.assertEqual(bill.invoice_date_due, _date("2026-10-01"))

    def test_posted_invoice_due_date_can_be_corrected(self):
        invoice = self.env["account.move"].create(
            self._invoice_vals("out_invoice", 1)
        )
        invoice.action_post()
        with Form(invoice, view=FORM_VIEW) as move_form:
            self.assertFalse(move_form._get_modifier("invoice_date_due", "readonly"))
            self.assertTrue(
                move_form._get_modifier("invoice_payment_term_id", "readonly")
            )
            move_form.invoice_date_due = _date("2026-10-31")

        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.invoice_date_due, _date("2026-10-31"))
        term_lines = invoice.line_ids.filtered(
            lambda line: line.display_type == "payment_term"
        )
        self.assertEqual(term_lines.mapped("date_maturity"), [_date("2026-10-31")])


@tagged("post_install", "-at_install")
class TestInvoiceCopy(InvoiceDueCopyCommon):
    """전표를 복제해 새 세금계산서를 만들어도 번호·승인번호·세금 구분이 꼬이지 않는다."""

    def test_copied_tax_invoices_are_saved_and_posted_as_new_documents(self):
        for serial, move_type in enumerate(DUE_LABELS, start=1):
            with self.subTest(move_type=move_type):
                origin = self.env["account.move"].create(
                    self._invoice_vals(move_type, serial)
                )
                origin.action_post()

                copied = origin.copy()
                self.assertEqual(copied.state, "draft")
                self.assertEqual(copied.move_type, move_type)
                self.assertFalse(copied.kr_approval_number)
                self.assertFalse(copied.kr_origin_number)
                self.assertEqual(copied.kr_doc_type, origin.kr_doc_type)
                self.assertEqual(copied.amount_total, origin.amount_total)

                # 화면에서 복제본을 열어 새 승인번호·일자·기한을 넣고 저장한다.
                with Form(copied, view=FORM_VIEW) as move_form:
                    move_form.invoice_date = _date("2026-09-10")
                    move_form.invoice_date_due = _date("2026-09-30")
                    move_form.kr_approval_number = self._approval(serial, "B")
                    if move_type in REFUND_TYPES:
                        move_form.kr_origin_number = self._approval(serial, "Y")
                copied.action_post()

                self.assertEqual(copied.state, "posted")
                self.assertNotEqual(copied.name, origin.name)
                self.assertEqual(copied.kr_approval_number, self._approval(serial, "B"))
                self.assertEqual(copied.invoice_date_due, _date("2026-09-30"))
                self.assertEqual(origin.kr_approval_number, self._approval(serial, "A"))
                self.assertEqual(copied.amount_total, origin.amount_total)

    def test_copy_keeps_manually_selected_tax_type(self):
        exempt_tax = self.env["account.tax"].create({
            "name": "면세 0% TF",
            "amount": 0.0,
            "amount_type": "percent",
            "type_tax_use": "sale",
            "company_id": self.company_data["company"].id,
        })
        invoice = self.env["account.move"].create(self._invoice_vals(
            "out_invoice", 11,
            invoice_line_ids=[Command.create({
                "name": "면세 품목",
                "quantity": 1,
                "price_unit": 1000.0,
                "tax_ids": [Command.set(exempt_tax.ids)],
            })],
        ))
        # 0% 세금만 있으면 자동 추정은 영세 — 담당자가 면세로 지정한 청구서
        self.assertEqual(invoice.kr_tax_type, "zero")
        invoice.write({"kr_tax_type": "exempt", "kr_tax_type_manual": True})

        copied = invoice.copy()
        self.assertEqual(copied.kr_tax_type, "exempt")
        self.assertTrue(copied.kr_tax_type_manual)
        # 복제본의 라인 세금을 다시 저장해도 면세가 영세로 바뀌지 않는다.
        copied.invoice_line_ids.write({"tax_ids": [Command.set(exempt_tax.ids)]})
        self.assertEqual(copied.kr_tax_type, "exempt")

    def test_copy_keeps_payment_term_and_recomputes_due_date(self):
        invoice = self.env["account.move"].create(self._invoice_vals(
            "out_invoice", 12, invoice_payment_term_id=self.term_30.id,
        ))
        self.assertEqual(invoice.invoice_date_due, _date("2026-10-01"))

        copied = invoice.copy()
        self.assertEqual(copied.invoice_payment_term_id, self.term_30)
        copied.invoice_date = _date("2026-11-01")
        self.assertEqual(copied.invoice_date_due, _date("2026-12-01"))

    def test_refund_created_by_reversal_is_not_affected(self):
        invoice = self.env["account.move"].create(self._invoice_vals(
            "out_invoice", 13, invoice_payment_term_id=self.term_30.id,
        ))
        invoice.action_post()
        refund = invoice._reverse_moves([{
            "date": invoice.date,
            "invoice_date": invoice.invoice_date,
            "invoice_payment_term_id": None,
        }])
        self.assertEqual(refund.move_type, "out_refund")
        self.assertFalse(refund.invoice_payment_term_id)
        self.assertFalse(refund.kr_approval_number)


@tagged("post_install", "-at_install")
class TestInvoiceCopyStudioApproval(InvoiceDueCopyCommon):
    """운영 DB에 남아 있는 Studio 승인번호 필드도 복제되지 않는다."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if STUDIO_FIELD not in cls.env["account.move"]._fields:
            cls.env["ir.model.fields"].create({
                "model_id": cls.env["ir.model"]._get_id("account.move"),
                "name": STUDIO_FIELD,
                "field_description": "세금계산서승인번호(Studio)",
                "ttype": "char",
                "state": "manual",
                "copied": True,
            })

    def test_studio_approval_number_is_not_copied(self):
        vals = self._invoice_vals("in_invoice", 21)
        vals[STUDIO_FIELD] = vals["kr_approval_number"]
        bill = self.env["account.move"].create(vals)
        self.assertEqual(bill[STUDIO_FIELD], vals["kr_approval_number"])

        copied = bill.copy()
        self.assertFalse(copied[STUDIO_FIELD])
        self.assertEqual(bill[STUDIO_FIELD], vals["kr_approval_number"])
