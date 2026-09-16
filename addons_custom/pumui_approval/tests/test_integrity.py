from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


class IntegrityCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(cls.env, login='phase2_author', groups='pumui_approval.group_pumui_user')
        cls.approver = new_test_user(cls.env, login='phase2_approver', groups='pumui_approval.group_pumui_user')
        cls.outsider = new_test_user(cls.env, login='phase2_outsider', groups='base.group_user')
        cls.partner = cls.env['res.partner'].create({'name': 'Phase2 partner'})
        cls.account = cls.env['account.account'].search([('account_type', '=', 'expense'), ('company_ids', 'in', cls.env.company.id)], limit=1)

    def _request(self, amount=100000, approve=True, **extra):
        vals = {'title': 'Phase2 request', 'partner_id': self.partner.id,
                'line_ids': [(0, 0, {'name': 'Phase2 expense', 'quantity': 1, 'price_unit': amount})],
                'approval_line_ids': [(0, 0, {'user_id': self.approver.id, 'sequence': 1})]}
        vals.update(extra)
        request = self.env['pumui.request'].with_user(self.author).create(vals)
        if approve:
            request.action_submit_approval()
            request.with_user(self.approver).action_approve_approval()
        return request

    def _bill(self, request, amount, **extra):
        vals = {'move_type': 'in_invoice', 'partner_id': self.partner.id,
                'company_id': self.env.company.id, 'pumui_id': request.id,
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': [(0, 0, {'name': 'Phase2 bill', 'account_id': self.account.id,
                                           'quantity': 1, 'price_unit': amount, 'tax_ids': [(5, 0, 0)]})]}
        vals.update(extra)
        return self.env['account.move'].create(vals)


@tagged('post_install', '-at_install')
class TestApprovalIntegrity(IntegrityCase):
    def test_default_context_cannot_inject_approval(self):
        old = self._request()
        p = self.env['pumui.request'].with_user(self.author).with_context(
            default_approval_request_id=old.approval_request_id.id,
            default_approval_state='approved', default_state='approved',
            default_amount_total=999999,
        ).create({'title': 'Phase2 context attack', 'partner_id': self.partner.id})
        self.assertEqual(p.approval_state, 'draft')
        self.assertNotEqual(p.approval_request_id, old.approval_request_id)
        line = self.env['iatf.approval.line'].with_user(self.author).with_context(default_state='approved').create({
            'request_id':p.approval_request_id.id,'user_id':self.approver.id})
        self.assertEqual(line.state, 'new')

    def test_state_and_context_forgery_are_blocked(self):
        p = self._request(approve=False)
        for user in (self.author, self.outsider, self.env.user):
            for context in ({}, {'_approval_transition': True}):
                with self.assertRaises(AccessError), self.cr.savepoint():
                    p.approval_request_id.with_user(user).with_context(**context).write({'state': 'approved'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.approval_line_ids.write({'state': 'approved'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.write({'approval_state': 'approved'})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['iatf.approval.request'].create({'res_model': p._name, 'res_id': p.id, 'state': 'approved'})

    def test_only_current_approver_and_current_revision_can_decide(self):
        p = self._request(approve=False)
        p.action_submit_approval()
        old = p.approval_request_id
        with self.assertRaises(UserError), self.cr.savepoint():
            p.action_approve_approval()
        p.line_ids.write({'quantity': 2})
        self.assertEqual(p.approval_state, 'draft')
        self.assertEqual(old.state, 'in_progress')
        with self.assertRaises(UserError), self.cr.savepoint():
            old.with_user(self.approver).action_approve()

    def test_detail_create_write_unlink_reset_and_preserve_history(self):
        for change in ('quantity', 'create', 'unlink'):
            p = self._request()
            old = p.approval_request_id
            snapshot = dict(old.snapshot)
            if change == 'quantity':
                p.line_ids.write({'quantity': 2})
            elif change == 'create':
                self.env['pumui.request.line'].with_user(self.author).create({'pumui_id': p.id, 'name': 'Extra', 'price_unit': 1})
            else:
                p.line_ids.unlink()
            self.assertEqual(p.approval_state, 'draft')
            self.assertEqual(p.approval_request_id.previous_request_id, old)
            self.assertEqual(old.state, 'approved')
            self.assertEqual(old.snapshot, snapshot)
            self.assertTrue(old.approved_date)
            self.assertEqual(old.line_ids.state, 'approved')

    def test_moving_line_invalidates_both_parents(self):
        first, second = self._request(), self._request()
        first.line_ids.write({'pumui_id': second.id})
        self.assertEqual(first.approval_state, 'draft')
        self.assertEqual(second.approval_state, 'draft')

    def test_computed_amount_and_invoice_link_forgery_blocked(self):
        p = self._request()
        bill = self._bill(p, 100000)
        for vals in ({'price_total': 1}, {'price_subtotal': 1}, {'invoiced': True}, {'invoice_line_id': bill.invoice_line_ids.id}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                p.line_ids.write(vals)
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.write({'amount_total': 999999})
        self.assertEqual(p.approval_state, 'approved')

    def test_relinking_and_old_history_edit_are_blocked(self):
        p, other = self._request(), self._request()
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.write({'approval_request_id': other.approval_request_id.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            p.approval_line_ids.sudo().write({'user_id': self.author.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            p.approval_request_id.sudo().unlink()
        old = p.approval_request_id
        p.write({'title': 'Changed title'})
        p.action_submit_approval()
        p.with_user(self.approver).action_approve_approval()
        self.assertEqual(p.approval_state, 'approved')
        self.assertEqual(old.snapshot['title'], 'Phase2 request')
        self.assertEqual(p.approval_request_id.snapshot['title'], 'Changed title')

    def test_outsider_cannot_change_route_or_reset(self):
        p = self._request(approve=False)
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.approval_request_id.with_user(self.outsider).read(['snapshot'])
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.approval_line_ids.with_user(self.outsider).write({'user_id': self.outsider.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.approval_request_id.with_user(self.outsider).action_reset_draft()

    def test_reject_preserves_decision_on_resubmission(self):
        p = self._request(approve=False)
        p.action_submit_approval()
        old = p.approval_request_id
        old.with_user(self.approver).action_reject('Needs correction')
        p.action_reset_approval()
        self.assertEqual(old.state, 'rejected')
        self.assertEqual(old.line_ids.note, 'Needs correction')
        self.assertEqual(p.approval_state, 'draft')

    def test_rejection_reason_edit_keeps_current_route(self):
        p = self._request(approve=False)
        p.action_submit_approval()
        old = p.approval_request_id
        p.with_user(self.approver).write({'rejection_reason': 'Correct the amount'})
        self.assertEqual(p.approval_request_id, old)
        self.assertEqual(p.approval_state, 'in_progress')
        p.with_user(self.approver).action_reject_approval()
        self.assertEqual(old.state, 'rejected')
        self.assertEqual(old.line_ids.note, 'Correct the amount')


@tagged('post_install', '-at_install')
class TestBillingIntegrity(IntegrityCase):
    def test_both_posting_routes_reject_unapproved(self):
        p = self._request(approve=False)
        bill = self._bill(p, 100000)
        for action in (bill.action_post, lambda: bill._post(soft=False)):
            with self.assertRaises(UserError), self.cr.savepoint():
                action()
            self.assertEqual(bill.state, 'draft')

    def test_split_bills_and_over_limit(self):
        p = self._request()
        first, second = self._bill(p, 40000), self._bill(p, 60000)
        first.action_post()
        second._post(soft=False)
        self.assertEqual((first | second).mapped('state'), ['posted', 'posted'])
        extra = self._bill(p, 1)
        with self.assertRaises(UserError), self.cr.savepoint():
            extra._post(soft=False)
        self.assertEqual(extra.state, 'draft')

    def test_batch_posting_checks_combined_amount(self):
        p = self._request()
        bills = self._bill(p, 60000) | self._bill(p, 60000)
        with self.assertRaises(UserError), self.cr.savepoint():
            bills._post(soft=False)
        self.assertEqual(bills.mapped('state'), ['draft', 'draft'])

    def test_refund_releases_limit_and_cannot_exceed_original(self):
        p = self._request()
        original = self._bill(p, 100000)
        original.action_post()
        refund = self._bill(p, 40000, move_type='in_refund', reversed_entry_id=original.id)
        refund.action_post()
        replacement = self._bill(p, 40000)
        replacement.action_post()
        self.assertEqual(replacement.state, 'posted')
        with self.assertRaises(UserError), self.cr.savepoint():
            original.button_draft()
        too_much = self._bill(p, 70000, move_type='in_refund', reversed_entry_id=original.id)
        with self.assertRaises(UserError), self.cr.savepoint():
            too_much._post(soft=False)
        with self.assertRaises(UserError), self.cr.savepoint():
            refund.button_draft()

    def test_unlinked_refund_and_wrong_scope_are_rejected(self):
        p = self._request()
        other = self.env['res.partner'].create({'name': 'Phase2 other partner'})
        for vals in ({'move_type': 'in_refund'}, {'move_type': 'out_invoice'}, {'partner_id': other.id}):
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self._bill(p, 100, **vals)

    def test_cancelled_bill_releases_limit(self):
        p = self._request()
        bill = self._bill(p, 100000)
        bill.action_post()
        bill.button_draft()
        bill.button_cancel()
        replacement = self._bill(p, 100000)
        replacement.action_post()
        self.assertEqual(replacement.state, 'posted')

    def test_posted_link_cannot_be_removed(self):
        p = self._request()
        bill = self._bill(p, 100000)
        bill.action_post()
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'pumui_id': False})

    def test_draft_link_cannot_be_removed_to_bypass_approval(self):
        p = self._request(approve=False)
        bill = self._bill(p, 100000)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill.write({'pumui_id': False})

    def test_auto_invoice_link_does_not_reset_approval(self):
        p = self._request().sudo()
        p.action_create_invoice()
        self.assertEqual(p.approval_state, 'approved')
        self.assertEqual(p.line_ids.invoice_line_id.move_id, p.move_ids)
        with self.assertRaises(UserError), self.cr.savepoint():
            p.line_ids.write({'pumui_id': self._request().id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            p.move_ids.write({'pumui_id': self._request().id})

    def test_invoice_detail_cannot_move_to_unrelated_parent(self):
        p = self._request().sudo()
        p.action_create_invoice()
        other = self._bill(self._request(), 1)
        with self.assertRaises(UserError), self.cr.savepoint():
            p.line_ids.invoice_line_id.write({'move_id': other.id})

    def test_legacy_approval_requires_new_evidence(self):
        p = self._request()
        self.cr.execute('UPDATE iatf_approval_request SET snapshot=NULL WHERE id=%s', [p.approval_request_id.id])
        p.approval_request_id.invalidate_recordset(['snapshot'])
        bill = self._bill(p, 100000)
        with self.assertRaises(UserError), self.cr.savepoint():
            bill._post(soft=False)
        p.action_reset_approval()
        p.action_submit_approval()
        p.with_user(self.approver).action_approve_approval()
        bill._post(soft=False)
        self.assertEqual(bill.state, 'posted')

    def test_company_currency_rounding_defines_limit(self):
        rounding = self.env.company.currency_id.rounding
        p = self._request(amount=100 * rounding + rounding / 10)
        bill = self._bill(p, 100 * rounding)
        bill.action_post()
        extra = self._bill(p, rounding)
        with self.assertRaises(UserError), self.cr.savepoint():
            extra._post(soft=False)

    def test_tax_inclusive_limit_and_rounding(self):
        tax = self.env['account.tax'].create({'name': 'Phase2 10%', 'amount': 10, 'type_tax_use': 'purchase'})
        p = self._request(approve=False)
        p.line_ids.write({'tax_ids': [(6, 0, tax.ids)]})
        p.action_submit_approval()
        p.with_user(self.approver).action_approve_approval()
        bill = self._bill(p, 100000)
        bill.invoice_line_ids.tax_ids = tax
        self.assertEqual(p.amount_total, bill.amount_total)
        bill._post(soft=False)
        self.assertEqual(bill.state, 'posted')

    def test_foreign_currency_uses_company_value(self):
        currency = self.env['res.currency'].create({'name': 'P2X', 'symbol': 'P2X', 'rounding': 0.01,
            'rate_ids': [(0, 0, {'name': fields.Date.today(), 'company_id': self.env.company.id, 'rate': 2})]})
        p = self._request(amount=1000)
        bill = self._bill(p, 2000, currency_id=currency.id)
        expected = currency._convert(bill.amount_total, p.currency_id, p.company_id, bill.date)
        # Currency rate uses the company's actual base rate, not an assumed KRW setup.
        p.line_ids.price_unit = expected
        p.action_submit_approval()
        p.with_user(self.approver).action_approve_approval()
        bill.action_post()
        self.assertEqual(bill.state, 'posted')
        self.assertEqual(p.currency_id.compare_amounts(p.invoiced_amount, expected), 0)
        self.assertTrue(p.currency_id.is_zero(p.amount_diff))
        extra = self._bill(p, 2000, currency_id=currency.id)
        with self.assertRaises(UserError), self.cr.savepoint():
            extra._post(soft=False)

    def test_tax_master_change_requires_new_approval(self):
        tax = self.env['account.tax'].create({'name': 'Phase2 changed tax', 'amount': 10, 'type_tax_use': 'purchase'})
        p = self._request(approve=False)
        p.line_ids.tax_ids = tax
        p.action_submit_approval()
        p.with_user(self.approver).action_approve_approval()
        tax.amount = 20
        bill = self._bill(p, 100000)
        bill.invoice_line_ids.tax_ids = tax
        with self.assertRaises(UserError), self.cr.savepoint():
            bill._post(soft=False)

    def test_tax_calculation_order_change_requires_new_approval(self):
        tax = self.env['account.tax'].create({'name': 'Phase21 ordered tax', 'amount': 10, 'type_tax_use': 'purchase'})
        p = self._request(approve=False)
        p.line_ids.tax_ids = tax
        p.action_submit_approval()
        p.with_user(self.approver).action_approve_approval()
        tax.sequence += 1
        with self.assertRaises(UserError), self.cr.savepoint():
            p.action_create_invoice()
