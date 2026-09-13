from datetime import timedelta

from odoo import fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestPaymentDueDisplay(AccountTestInvoicingCommon):

    def _create_posted_invoice(self, move_type, due_date):
        invoice = self.init_invoice(
            move_type=move_type,
            invoice_date=due_date - timedelta(days=1),
            amounts=[100.0],
        )
        invoice.action_post()
        invoice.invoice_date_due = due_date
        self.assertEqual(invoice.invoice_date_due, due_date)
        return invoice

    def _register_payment(self, invoice, payment_date):
        return self.env["account.payment.register"].with_context(
            active_model="account.move",
            active_ids=invoice.ids,
        ).create({
            "payment_date": payment_date,
        })._create_payments()

    def test_unpaid_invoice_uses_due_date_and_only_past_date_is_red(self):
        today = fields.Date.context_today(self.env.user)
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)

        overdue_invoice = self._create_posted_invoice("out_invoice", yesterday)
        due_today_invoice = self._create_posted_invoice("out_invoice", today)
        future_invoice = self._create_posted_invoice("in_invoice", tomorrow)

        self.assertEqual(overdue_invoice.kr_payment_display_date, yesterday)
        self.assertTrue(overdue_invoice.kr_payment_overdue)
        self.assertEqual(due_today_invoice.kr_payment_display_date, today)
        self.assertFalse(due_today_invoice.kr_payment_overdue)
        self.assertEqual(future_invoice.kr_payment_display_date, tomorrow)
        self.assertFalse(future_invoice.kr_payment_overdue)

    def test_paid_invoice_uses_last_actual_payment_date_and_is_not_red(self):
        today = fields.Date.context_today(self.env.user)
        due_date = today - timedelta(days=10)
        first_payment_date = today - timedelta(days=2)
        final_payment_date = today - timedelta(days=1)
        invoice = self._create_posted_invoice("out_invoice", due_date)

        self.env["account.payment.register"].with_context(
            active_model="account.move",
            active_ids=invoice.ids,
        ).create({
            "amount": 40.0,
            "payment_date": first_payment_date,
        })._create_payments()
        self._register_payment(invoice, final_payment_date)

        self.assertTrue(invoice.currency_id.is_zero(invoice.amount_residual))
        self.assertEqual(invoice.kr_payment_display_date, final_payment_date)
        self.assertFalse(invoice.kr_payment_overdue)
