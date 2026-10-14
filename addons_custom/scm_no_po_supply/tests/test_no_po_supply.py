"""Candidate regression tests. Execute in an isolated copy, never shared UAT."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command, api, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user
from odoo.addons.scm_no_po_supply.controllers import portal


@tagged('post_install', '-at_install')
class TestNoPoSupply(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True,
            mail_notrack=True, mail_create_nosubscribe=True, mail_notify_force_send=False))
        cls.company = cls.env.company
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.vendor = cls.env['res.partner'].create({'name': 'No PO vendor', 'supplier_rank': 1,
            'is_supplier_portal': True, 'supplier_portal_company_ids': [Command.set(cls.company.ids)]})
        cls.other_vendor = cls.env['res.partner'].create({'name': 'No PO other vendor', 'supplier_rank': 1,
            'is_supplier_portal': True, 'supplier_portal_company_ids': [Command.set(cls.company.ids)]})
        cls.category = cls.env['product.category'].create({'name': 'No PO manual valuation',
            'property_valuation': 'manual_periodic'})
        cls.part = cls.env['product.product'].create({'name': 'No PO component', 'type': 'consu',
            'is_storable': True, 'categ_id': cls.category.id, 'standard_price': 10})
        cls.env['product.supplierinfo'].create({'partner_id': cls.vendor.id,
            'company_id': cls.company.id, 'product_tmpl_id': cls.part.product_tmpl_id.id, 'price': 10})
        cls.agreement = cls.env['scm.no.po.agreement'].create({'name': 'Explicit component agreement',
            'company_id': cls.company.id, 'partner_id': cls.vendor.id, 'product_id': cls.part.id,
            'picking_type_id': cls.wh.in_type_id.id, 'reference': 'TEST-CONTRACT-NO-PO', 'component_confirmed': True,
            'date_start': '2026-01-01', 'date_end': '2026-12-31'})
        cls.stock_user = new_test_user(cls.env, login='no_po_stock_user', groups='stock.group_stock_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.portal_user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'No PO portal', 'login': 'no-po-vendor-portal', 'partner_id': cls.vendor.id,
            'company_id': cls.company.id, 'company_ids': [Command.set(cls.company.ids)],
            'groups_id': [Command.set(cls.env.ref('base.group_portal').ids)]})

    def notice(self, qty=10, issue=True, **values):
        self.agreement.active = True
        data = {'name': 'REQ-' + str(uuid.uuid4()), 'agreement_id': self.agreement.id,
            'uom_id': self.part.uom_id.id, 'quantity': qty, 'need_date': '2026-09-25',
            'source_reference': 'OEM plan rev1; demand item ABC; base units'}
        data.update(values)
        notice = self.env['scm.no.po.notice'].create(data)
        if issue:
            notice.action_issue()
        return notice

    def asn(self, notice, qty=10, **values):
        vals = {'partner_id': self.vendor.id, 'company_id': self.company.id,
            'line_ids': [Command.create({'product_id': self.part.id, 'qty': qty,
                'no_po_notice_id': notice.id})]}
        vals.update(values)
        return self.env['supplier.asn'].create(vals)

    def done(self, picking, quantity):
        move = picking.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
        self.assertEqual(len(move), 1)
        move.quantity = quantity
        move.picked = True
        move._action_done()
        return move

    def test_default_agreement_is_inactive(self):
        self.assertFalse(self.agreement.active)
        notice = self.notice(issue=False)
        self.agreement.active = False
        with self.assertRaises(UserError), self.cr.savepoint():
            notice.action_issue()

    def test_notice_snapshot_survives_forecast_deletion(self):
        forecast = self.env['supplier.demand.forecast'].create({'company_id': self.company.id,
            'partner_id': self.vendor.id, 'product_id': self.part.id, 'date': '2026-09-25', 'qty_required': 10})
        notice = self.notice(source_kind='forecast', source_reference='Forecast source copied: quantity10 date2026-09-25')
        snapshot = notice.snapshot
        forecast.unlink()
        self.assertEqual(notice.snapshot, snapshot)
        self.assertEqual(json.loads(snapshot)['quantity'], 10)
        self.assertEqual(json.loads(snapshot)['forecast']['qty_required'], 10)
        for vals in [{'quantity': 20}, {'snapshot': '{}'}, {'state': 'draft'}]:
            with self.assertRaises(UserError), self.cr.savepoint():
                notice.write(vals)
        with self.assertRaises(UserError), self.cr.savepoint():
            notice.unlink()

    def test_draft_cannot_back_asn(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.asn(self.notice(issue=False))

    def test_expired_agreement_date_rejected(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.notice(need_date='2027-01-01')

    def test_notice_unit_and_nonfinite_rejected(self):
        wrong = self.env.ref('uom.product_uom_kgm')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.notice(uom_id=wrong.id)
        off_precision = 1 + self.part.uom_id.rounding / 2
        for quantity in [0, -1, float('inf'), float('nan'), off_precision]:
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.notice(qty=quantity)

    def test_agreement_scope_cannot_change_after_notice(self):
        self.notice()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.agreement.reference = 'changed'

    def test_supplier_and_product_scope(self):
        notice = self.notice()
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.asn(notice, partner_id=self.other_vendor.id)
        other_part = self.env['product.product'].create({'name': 'Different component', 'is_storable': True})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['supplier.asn'].create({'partner_id': self.vendor.id,
                'line_ids': [Command.create({'product_id': other_part.id, 'qty': 10, 'no_po_notice_id': notice.id})]})

    def test_asn_quantity_reserved_before_receipt(self):
        notice = self.notice()
        self.asn(notice, 6)
        self.assertEqual(notice.available_quantity, 4)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.asn(notice, 5)
        self.asn(notice, 4)
        self.assertEqual(notice.available_quantity, 0)

    def test_create_picking_double_click_one_receipt_no_po(self):
        notice = self.notice()
        asn = self.asn(notice)
        po_count = self.env['purchase.order'].search_count([])
        first = asn.action_create_picking()
        second = asn.action_create_picking()
        self.assertEqual(first['res_id'], second['res_id'])
        self.assertEqual(len(asn.line_ids.move_ids), 1)
        self.assertFalse(asn.line_ids.move_ids.purchase_line_id)
        self.assertEqual(self.env['purchase.order'].search_count([]), po_count)
        self.assertNotEqual(asn.line_ids.move_ids.state, 'done')
        self.assertFalse(asn.line_ids.move_ids.picked)

    def test_receive_keeps_accounting_zero(self):
        asn = self.asn(self.notice())
        asn.action_create_picking()
        before = self.env['account.move'].search_count([])
        self.done(asn.picking_id, 10)
        self.assertEqual(asn.state, 'received')
        self.assertEqual(asn.line_ids.no_po_notice_id.received_quantity, 10)
        self.assertEqual(self.env['account.move'].search_count([]), before)

    def test_cancel_cancels_stock_demand_and_releases_notice(self):
        notice = self.notice()
        asn = self.asn(notice)
        asn.action_create_picking()
        moves = asn.line_ids.move_ids
        asn.action_cancel()
        self.assertEqual(asn.state, 'cancelled')
        self.assertTrue(all(m.state == 'cancel' for m in moves))
        self.assertEqual(moves.supplier_asn_line_id, asn.line_ids)
        self.assertEqual(notice.available_quantity, 10)
        self.asn(notice)
        with self.assertRaises(UserError), self.cr.savepoint():
            asn.action_create_picking()

    def test_valuation_change_after_allocation_blocks_receipt(self):
        asn = self.asn(self.notice())
        asn.action_create_picking()
        self.category.property_valuation = 'real_time'
        with self.assertRaises(UserError), self.cr.savepoint():
            self.done(asn.picking_id, 10)
        self.assertNotEqual(asn.state, 'received')

    def test_overdelivery_cannot_inflate_actual_receipt(self):
        asn = self.asn(self.notice())
        asn.action_create_picking()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.done(asn.picking_id, 11)
        self.assertFalse(asn.line_ids.move_ids.filtered(lambda m: m.state == 'done'))

    def test_partial_receipt_remaining_not_duplicate(self):
        notice = self.notice()
        asn = self.asn(notice)
        asn.action_create_picking()
        self.done(asn.picking_id, 4)
        self.assertEqual(asn.state, 'announced')
        self.assertEqual(notice.received_quantity, 4)
        self.assertEqual(notice.available_quantity, 0)
        action = asn.action_create_picking()
        remaining = self.env['stock.picking'].browse(action['res_id'])
        self.done(remaining, 6)
        self.assertEqual(notice.received_quantity, 10)
        self.assertEqual(asn.state, 'received')
        with self.assertRaises(UserError), self.cr.savepoint():
            notice.action_cancel()

    def test_cancel_before_receipt_revision_preserves_original(self):
        original = self.notice()
        self.asn(original).action_create_picking()
        snapshot = original.snapshot
        original.action_cancel()
        new = self.notice(qty=8, revision_of_id=original.id, revision_reason='OEM plan reduction')
        self.assertEqual(original.snapshot, snapshot)
        self.assertEqual(new.revision_of_id, original)
        self.assertEqual(new.state, 'issued')

    def test_stock_user_cannot_issue_or_mutate_notice(self):
        notice = self.notice(issue=False)
        with self.assertRaises(AccessError), self.cr.savepoint():
            notice.with_user(self.stock_user).action_issue()
        with self.assertRaises(AccessError), self.cr.savepoint():
            notice.with_user(self.stock_user).write({'quantity': 12})

    def test_portal_submission_idempotent_and_payload_conflict(self):
        notice = self.notice()
        key = str(uuid.uuid4())
        first = notice._supplier_create_asn(4, '2026-09-25', 'LOT-A', key)
        second = notice._supplier_create_asn(4, '2026-09-25', 'LOT-A', key)
        self.assertEqual(first, second)
        self.assertEqual(notice.allocated_quantity, 4)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            notice._supplier_create_asn(5, '2026-09-25', 'LOT-A', key)

    def test_portal_sudo_still_cannot_impersonate_supplier(self):
        notice = self.notice()
        # No capability token: sudo retains actual portal actor and partner checks.
        other_user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other portal', 'login': 'no-po-other-portal', 'partner_id': self.other_vendor.id,
            'company_id': self.company.id, 'company_ids': [Command.set(self.company.ids)],
            'groups_id': [Command.set(self.env.ref('base.group_portal').ids)]})
        with self.assertRaises(AccessError), self.cr.savepoint():
            notice.with_user(other_user).sudo()._supplier_create_asn(4, '2026-09-25', '', str(uuid.uuid4()))

    def test_portal_route_has_scoped_source_and_idempotency(self):
        notice = self.notice()
        req = SimpleNamespace(env=api.Environment(self.env.cr, self.portal_user.id, dict(self.env.context,
            allowed_company_ids=self.company.ids)), redirect=lambda value: value,
            render=lambda template, values: 'error: %s' % values.get('error', ''))
        req.update_env = lambda context=None, **kw: setattr(req, 'env', req.env(context=context))
        # Authentication uses the original controller module request object too.
        from odoo.addons.supplier_portal_purchase.controllers import portal as original_portal
        post = {'notice_id': str(notice.id), 'quantity': '3', 'expected_date': '2026-09-25',
            'request_key': str(uuid.uuid4())}
        with patch.object(portal, 'request', req), patch.object(original_portal, 'request', req):
            before = self.env['supplier.asn'].search_count([])
            first = portal.NoPoPortal().create_asn(**post)
            second = portal.NoPoPortal().create_asn(**post)
            self.assertEqual(self.env['supplier.asn'].search_count([]), before + 1)
            first_location = (getattr(first, 'location', None)
                or (first.get_data(as_text=True) if hasattr(first, 'get_data') else first))
            second_location = (getattr(second, 'location', None)
                or (second.get_data(as_text=True) if hasattr(second, 'get_data') else second))
            self.assertEqual(first_location, second_location)
            self.assertIn('/supplier/asn/', first_location)
            post['notice_id'] = '999999999'
            denied = portal.NoPoPortal().create_asn(**post)
            if isinstance(denied, dict):
                self.assertIn('error', denied)
            else:
                self.assertEqual(denied.status_code, 200)
            self.assertEqual(self.env['supplier.asn'].search_count([]), before + 1)
        self.assertEqual(notice.allocated_quantity, 3)

    def test_existing_po_asn_path_preserved(self):
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id, 'company_id': self.company.id,
            'picking_type_id': self.wh.in_type_id.id, 'order_line': [Command.create({
                'name': self.part.name, 'product_id': self.part.id, 'product_qty': 10,
                'product_uom': self.part.uom_id.id, 'price_unit': 10, 'date_planned': fields.Datetime.now()})]})
        po.button_confirm()
        asn = self.env['supplier.asn'].create({'partner_id': self.vendor.id,
            'line_ids': [Command.create({'product_id': self.part.id, 'qty': 4, 'purchase_line_id': po.order_line.id})]})
        asn.action_create_picking()
        self.assertEqual(asn.line_ids.move_ids.purchase_line_id, po.order_line)
        self.assertFalse(asn.line_ids.no_po_notice_id)
        moves = asn.line_ids.move_ids
        asn.action_cancel()
        self.assertFalse(moves.supplier_asn_line_id)
        self.assertFalse(moves.filtered(lambda m: m.state == 'cancel'))

    def test_new_po_for_active_component_agreement_rejected(self):
        self.notice()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['purchase.order'].create({'partner_id': self.vendor.id,
                'company_id': self.company.id, 'order_line': [Command.create({
                    'name': self.part.name, 'product_id': self.part.id, 'product_qty': 10,
                    'product_uom': self.part.uom_id.id, 'price_unit': 10,
                    'date_planned': '2026-09-25 00:00:00'})]})

    def test_direct_purchase_approval_and_line_growth_are_rejected(self):
        po = self.env['purchase.order'].create({'partner_id': self.vendor.id,
            'company_id': self.company.id, 'order_line': [Command.create({
                'name': self.part.name, 'product_id': self.part.id, 'product_qty': 4,
                'product_uom': self.part.uom_id.id, 'price_unit': 10,
                'date_planned': '2026-09-25 00:00:00'})]})
        # Reproduce a stale/concurrent state at the final guard, bypassing the
        # earlier agreement-activation check only in this test setup.
        self.env.cr.execute('UPDATE scm_no_po_agreement SET active=TRUE WHERE id=%s',
            (self.agreement.id,))
        self.agreement.invalidate_recordset(['active'])
        with self.assertRaises(UserError), self.cr.savepoint():
            po.button_approve()
        with self.assertRaises(UserError), self.cr.savepoint():
            po.order_line.write({'product_qty': 5})

    def test_open_rfq_blocks_agreement_activation(self):
        self.env['purchase.order'].create({'partner_id': self.vendor.id,
            'company_id': self.company.id, 'order_line': [Command.create({
                'name': self.part.name, 'product_id': self.part.id, 'product_qty': 4,
                'product_uom': self.part.uom_id.id, 'price_unit': 10,
                'date_planned': '2026-09-25 00:00:00'})]})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.agreement.write({'active': True})

    def test_purchase_partner_change_cannot_enter_active_scope(self):
        po = self.env['purchase.order'].create({'partner_id': self.other_vendor.id,
            'company_id': self.company.id, 'order_line': [Command.create({
                'name': self.part.name, 'product_id': self.part.id, 'product_qty': 4,
                'product_uom': self.part.uom_id.id, 'price_unit': 10,
                'date_planned': '2026-09-25 00:00:00'})]})
        self.agreement.write({'active': True})
        with self.assertRaises(UserError), self.cr.savepoint():
            po.write({'partner_id': self.vendor.id})

    def test_partial_close_then_new_remaining_notice(self):
        notice = self.notice()
        asn = self.asn(notice)
        asn.action_create_picking()
        self.done(asn.picking_id, 4)
        notice.action_close_remaining()
        self.assertEqual(notice.state, 'closed')
        self.assertEqual(asn.state, 'closed')
        self.assertEqual(notice.received_quantity, 4)
        self.assertEqual(notice.available_quantity, 0)
        self.assertFalse(asn.line_ids.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')))
        replacement = self.notice(qty=3, revision_of_id=notice.id,
            revision_reason='Remaining demand reduced from6 to3; delivered4 preserved')
        self.assertEqual(replacement.quantity, 3)
        self.assertEqual(replacement.available_quantity, 3)
        self.assertEqual(notice.received_quantity, 4)

    def test_resin_flag_cannot_enter_component_agreement_when_installed(self):
        if 'settle_by_ton' not in self.part.product_tmpl_id._fields:
            self.skipTest('injection_worksite not installed; repeat on UAT module composition')
        self.part.product_tmpl_id.settle_by_ton = True
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.agreement.active = True
