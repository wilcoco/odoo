"""Real stock posting and isolated failure boundaries; synthetic records only."""
import base64
import hashlib
from unittest.mock import patch

import psycopg2

from odoo import Command
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


def reject_quality():
    raise UserError('Synthetic IATF rejection')


@tagged('post_install', '-at_install')
class TestPassiveVerification(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.iatf_passive_enabled = True
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.unit = cls.env.ref('uom.product_uom_unit')
        cls.supplier_location = cls.env.ref('stock.stock_location_suppliers')
        cls.customer_location = cls.env.ref('stock.stock_location_customers')
        cls.partner = cls.env['res.partner'].create({'name': 'Passive synthetic partner'})
        cls.product = cls.env['product.product'].create({
            'name': 'Passive synthetic item', 'is_storable': True, 'tracking': 'none'})
        cls.reader = new_test_user(
            cls.env(context=dict(cls.env.context, no_reset_password=True)),
            login='iatf_passive_reader', groups='base.group_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.Log = cls.env['iatf.passive.log']

    def _picking(self, outgoing=False, product=None):
        product = product or self.product
        kind = self.wh.out_type_id if outgoing else self.wh.in_type_id
        source = self.wh.lot_stock_id if outgoing else self.supplier_location
        destination = self.customer_location if outgoing else self.wh.lot_stock_id
        if outgoing:
            self.env['stock.quant']._update_available_quantity(product, source, 5)
        picking = self.env['stock.picking'].create({
            'company_id': self.company.id, 'picking_type_id': kind.id,
            'partner_id': self.partner.id, 'location_id': source.id,
            'location_dest_id': destination.id,
            'move_ids': [Command.create({
                'name': 'Passive synthetic move', 'product_id': product.id,
                'product_uom_qty': 2, 'product_uom': self.unit.id,
                'location_id': source.id, 'location_dest_id': destination.id})]})
        picking.action_confirm()
        picking.move_ids.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': picking.move_ids.id, 'picking_id': picking.id,
            'product_id': product.id, 'product_uom_id': self.unit.id,
            'quantity': 2, 'location_id': source.id, 'location_dest_id': destination.id})
        picking.move_ids.picked = True
        return picking

    def _logs(self, record, outcome=None):
        domain = [('res_model', '=', record._name), ('res_id', 'in', record.ids)]
        if outcome:
            domain.append(('outcome', '=', outcome))
        return self.Log.search(domain)

    def test_receipt_keeps_destination_and_records_observation(self):
        picking = self._picking()
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(picking.move_ids.location_dest_id, self.wh.lot_stock_id)
        self.assertEqual(picking.move_line_ids.location_dest_id, self.wh.lot_stock_id)
        self.assertFalse(picking.iqc_pending_location_id)
        self.assertFalse(picking.move_line_ids.iqc_receipt_managed)
        self.assertFalse(picking.iqc_inspection_ids)
        logs = self._logs(picking.move_ids, 'observed')
        self.assertTrue(logs)
        self.assertTrue(all(log.source_id for log in logs))
        self.assertEqual(self.env['stock.quant']._get_available_quantity(
            self.product, self.wh.lot_stock_id), 2)

    def test_disabled_receipt_restores_iqc_quarantine(self):
        self.company.iatf_passive_enabled = False
        picking = self._picking()
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertTrue(picking.iqc_pending_location_id)
        self.assertEqual(picking.move_line_ids.location_dest_id, picking.iqc_pending_location_id)
        self.assertTrue(picking.move_line_ids.iqc_receipt_managed)
        self.assertEqual(len(picking.iqc_inspection_ids), 1)
        self.assertFalse(self._logs(picking.move_ids))

    def test_outgoing_without_approval_posts_and_logs(self):
        picking = self._picking(outgoing=True)
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertFalse(picking.oqc_inspection_ids)
        self.assertFalse(picking.outgoing_shipping_inspection_ids)
        logs = self._logs(picking, 'bypassed')
        self.assertTrue(logs)
        self.assertTrue(all(log.error_message for log in logs))
        self.assertEqual(self.env['stock.quant']._get_available_quantity(
            self.product, self.wh.lot_stock_id), 3)

    def test_disabled_outgoing_requires_approval(self):
        self.company.iatf_passive_enabled = False
        picking = self._picking(outgoing=True)
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.with_context(skip_backorder=True).button_validate()
        self.assertNotEqual(picking.state, 'done')
        self.assertFalse(self._logs(picking))

    def test_stock_operator_without_quality_roles_can_ship_with_audit_actor(self):
        operator = new_test_user(
            self.env(context=dict(self.env.context, no_reset_password=True)),
            login='iatf_passive_shipping_operator', groups='stock.group_stock_user',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        self.assertFalse(operator.has_group('base.group_system'))
        picking = self._picking(outgoing=True)
        picking.with_user(operator).with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, 'done')
        logs = self._logs(picking, 'bypassed')
        self.assertTrue(logs)
        self.assertEqual(logs.user_id, operator)
        self.assertTrue(set(logs.mapped('error_type')) <= {'AccessError', 'UserError'})
        self.assertFalse(picking.oqc_inspection_ids)
        self.assertFalse(picking.outgoing_shipping_inspection_ids)

    def test_native_lot_requirement_remains(self):
        tracked = self.env['product.product'].create({
            'name': 'Passive tracked item', 'is_storable': True, 'tracking': 'lot'})
        picking = self._picking(product=tracked)
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.with_context(skip_backorder=True).button_validate()
        self.assertNotEqual(picking.state, 'done')
        self.assertFalse(self._logs(picking.move_ids))

    def test_auxiliary_failure_rolls_back_partial_write(self):
        original_name = self.partner.name

        def partial_write():
            self.partner.write({'name': 'Must be rolled back'})
            raise ValueError('Synthetic auxiliary failure')

        self.assertEqual(self.Log._run(
            self.partner, partial_write, '시험', 'aux rollback',
            mode='auxiliary', fallback='continued'), 'continued')
        self.assertEqual(self.partner.name, original_name)
        log = self._logs(self.partner, 'auxiliary')
        self.assertEqual(len(log), 1)
        self.assertEqual(log.error_type, 'ValueError')
        self.assertIn('Synthetic auxiliary failure', log.error_message)

    def test_unlogged_pass_cannot_post(self):
        picking = self._picking(outgoing=True)
        available_before = self.env['stock.quant']._get_available_quantity(
            self.product, self.wh.lot_stock_id)
        with patch.object(type(self.Log), '_record', side_effect=UserError('Log persistence unavailable')):
            with self.assertRaisesRegex(UserError, 'Log persistence unavailable'), self.cr.savepoint():
                picking.with_context(skip_backorder=True).button_validate()
        self.assertNotEqual(picking.state, 'done')
        self.assertEqual(self.env['stock.quant']._get_available_quantity(
            self.product, self.wh.lot_stock_id), available_before)

    def test_gate_does_not_swallow_acl_or_database_errors(self):
        for error in (AccessError('ACL'), AccessDenied('auth'),
                      psycopg2.IntegrityError('SQL')):
            with self.subTest(error=type(error).__name__):
                def reject():
                    raise error

                with self.assertRaises(type(error)):
                    self.Log._run(self.partner, reject, '시험', 'native error')
        self.assertFalse(self._logs(self.partner))

    def test_isolated_gate_python_error_is_logged(self):
        def broken_quality_callback():
            raise ValueError('Broken IATF validation implementation')

        self.assertTrue(self.Log._run(
            self.partner, broken_quality_callback, '시험', 'isolated quality callback'))
        log = self._logs(self.partner, 'bypassed')
        self.assertEqual(len(log), 1)
        self.assertEqual(log.error_type, 'ValueError')
        self.assertIn('Broken IATF validation implementation', log.error_message)

    def test_auxiliary_does_not_swallow_auth_or_database_errors(self):
        for error in (AccessDenied('auth'), psycopg2.IntegrityError('SQL')):
            with self.subTest(error=type(error).__name__):
                def reject():
                    raise error

                with self.assertRaises(type(error)):
                    self.Log._run(self.partner, reject, '시험', 'aux native error', mode='auxiliary')
        self.assertFalse(self._logs(self.partner))

    def test_configuration_requires_system_user_and_is_logged(self):
        with self.assertRaises(AccessError):
            self.company.with_user(self.reader).write({'iatf_passive_enabled': False})
        self.assertTrue(self.company.iatf_passive_enabled)
        self.company.iatf_passive_enabled = False
        self.assertTrue(self._logs(self.company, 'configuration'))
        with self.assertRaises(UserError):
            self.Log._run(self.partner, reject_quality, '시험', 'disabled gate')
        self.assertFalse(self._logs(self.partner))

    def test_log_company_rule_and_callback_scope(self):
        other_company = self.env['res.company'].create({'name': 'Passive isolated company'})
        other_record = self.env['res.partner'].create({
            'name': 'Other company business record', 'company_id': other_company.id})
        log = self.Log._record(other_record, '시험', 'company rule', 'rejected', reject_quality)
        reader_log = self.Log.with_user(self.reader).with_context(allowed_company_ids=self.company.ids)
        self.assertFalse(reader_log.search([('id', '=', log.id)]))
        with self.assertRaises(AccessError):
            reader_log._run(other_record.with_user(self.reader), reject_quality, '시험', 'company scope')

    def test_source_content_hash_and_log_are_immutable(self):
        self.Log._run(self.partner, reject_quality, '시험', 'source evidence')
        log = self._logs(self.partner)
        source = log.source_id
        self.assertTrue(source)
        self.assertGreater(log.source_line, 0)
        content = base64.b64decode(source.content)
        self.assertEqual(hashlib.sha256(content).hexdigest(), source.sha256)
        self.assertIn(b'def reject_quality', content)
        self.assertIn('iatf_passive_verify_test/', source.path)
        attachment = self.env['ir.attachment'].search([
            ('res_model', '=', 'iatf.passive.source'), ('res_id', '=', source.id),
            ('res_field', '=', 'content')])
        self.assertTrue(attachment)
        for record, vals in ((source, {'filename': 'changed.py'}), (log, {'error_message': 'changed'})):
            with self.assertRaises(AccessError):
                record.write(vals)
            with self.assertRaises(AccessError):
                record.unlink()
        with self.assertRaises(AccessError):
            attachment.write({'datas': base64.b64encode(b'changed')})
        with self.assertRaises(AccessError):
            attachment.unlink()

    def test_original_action_respects_target_acl(self):
        picking = self._picking()
        log = self.Log._record(picking, '시험', 'original target ACL', 'rejected', reject_quality)
        visible_log = log.with_user(self.reader)
        visible_log.check_access('read')
        with self.assertRaises(AccessError):
            visible_log.action_open_record()
        with self.assertRaises(AccessError):
            visible_log.action_open_attachments()
        action = log.action_open_record()
        self.assertEqual((action['res_model'], action['res_id']), ('stock.picking', picking.id))

    def test_quality_approval_is_not_fabricated(self):
        inspection = self.env['iatf.process.inspection'].create({
            'company_id': self.company.id, 'product_id': self.product.id,
            'quantity_produced': 1, 'quantity_inspected': 0})
        with self.assertRaises(UserError):
            inspection._approval_check_approved('quality document completion')
        self.assertNotEqual(inspection.approval_state, 'approved')

    def test_pending_bom_change_request_blocks_only_when_disabled(self):
        bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product.product_tmpl_id.id, 'product_qty': 1})
        request = self.env['iatf.change.request'].create({
            'title': 'Synthetic pending BOM change', 'change_type': 'method',
            'description': '<p>Synthetic change</p>', 'reason': '<p>Regression test</p>',
            'affected_product_ids': [Command.set(self.product.ids)]})
        self.company.iatf_passive_enabled = False
        with self.assertRaisesRegex(UserError, '미승인 변경요청'), self.cr.savepoint():
            bom.write({'product_qty': 2})
        self.assertEqual(bom.product_qty, 1)
        self.company.iatf_passive_enabled = True
        bom.write({'product_qty': 2})
        self.assertEqual(bom.product_qty, 2)
        self.assertEqual(request.state, 'draft')
        self.assertTrue(self._logs(bom, 'bypassed'))
        self.assertEqual(self.env['iatf.change.request'].search_count([
            ('affected_product_ids', 'in', self.product.ids)]), 2)

    def test_bom_write_survives_automatic_change_request_create_acl(self):
        # The operator may read the change gate, but may not create quality CRs.
        read_group = self.env['res.groups'].create({'name': 'Synthetic CR reader only'})
        self.env['ir.model.access'].create({
            'name': 'Synthetic CR read access',
            'model_id': self.env['ir.model']._get_id('iatf.change.request'),
            'group_id': read_group.id, 'perm_read': True,
            'perm_create': False, 'perm_write': False, 'perm_unlink': False})
        operator = new_test_user(
            self.env(context=dict(self.env.context, no_reset_password=True)),
            login='iatf_passive_bom_operator', groups='mrp.group_mrp_manager',
            company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        operator.write({'groups_id': [Command.link(read_group.id)]})
        self.assertFalse(self.env['iatf.change.request'].with_user(operator).has_access('create'))
        bom = self.env['mrp.bom'].create({
            'company_id': self.company.id,
            'product_tmpl_id': self.product.product_tmpl_id.id, 'product_qty': 1})
        bom.with_user(operator).write({'product_qty': 3})
        self.assertEqual(bom.product_qty, 3)
        log = self._logs(bom, 'auxiliary')
        self.assertEqual(len(log), 1)
        self.assertEqual(log.error_type, 'AccessError')
        self.assertEqual(log.user_id, operator)
        self.assertFalse(self.env['iatf.change.request'].search([
            ('affected_product_ids', 'in', self.product.ids)]))

    def test_failed_previous_ipqc_blocks_start_only_when_disabled(self):
        production = self.env['mrp.production'].create({
            'product_id': self.product.id, 'product_qty': 2,
            'product_uom_id': self.unit.id, 'company_id': self.company.id})
        center = self.env['mrp.workcenter'].create({
            'name': 'Passive synthetic workcenter', 'company_id': self.company.id})
        orders = self.env['mrp.workorder'].create([
            {'name': 'Synthetic previous operation', 'production_id': production.id,
             'product_uom_id': self.unit.id, 'workcenter_id': center.id, 'sequence': 10},
            {'name': 'Synthetic next operation', 'production_id': production.id,
             'product_uom_id': self.unit.id, 'workcenter_id': center.id,
             'sequence': 20, 'duration_expected': 5}])
        previous, current = orders
        previous.write({'state': 'done', 'qty_produced': 2})
        inspection = self.env['iatf.process.inspection'].create({
            'company_id': self.company.id, 'product_id': self.product.id,
            'production_id': production.id, 'workorder_id': previous.id,
            'inspection_stage': 'ipqc', 'quantity_produced': 2,
            'quantity_inspected': 2, 'quantity_rejected': 2, 'result': 'fail',
            'line_ids': [Command.create({'characteristic_name': 'Synthetic surface',
                'measured_value': 'Crack observed', 'result': 'fail'})]})
        inspection.action_start_inspection()
        inspection.action_decide()
        self.company.iatf_passive_enabled = False
        with self.assertRaisesRegex(UserError, 'IPQC'), self.cr.savepoint():
            current.button_start()
        self.assertNotEqual(current.state, 'progress')
        self.company.iatf_passive_enabled = True
        current.button_start()
        self.assertEqual(current.state, 'progress')
        self.assertEqual((inspection.state, inspection.result), ('decided', 'fail'))
        self.assertTrue(self._logs(current, 'bypassed'))

    def test_held_lot_consumption_passes_without_clearing_hold(self):
        raw = self.env['product.product'].create({
            'name': 'Passive held component', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({
            'name': 'SYNTHETIC-PASSIVE-HOLD', 'product_id': raw.id,
            'company_id': self.company.id, 'quality_hold': True, 'hold_reason': 'Synthetic hold'})
        production = self.env['mrp.production'].create({
            'product_id': self.product.id, 'product_qty': 2,
            'product_uom_id': self.unit.id, 'company_id': self.company.id})
        destination = self.env['stock.location'].create({
            'name': 'Passive synthetic production location', 'usage': 'production',
            'company_id': self.company.id})
        self.env['stock.quant']._update_available_quantity(raw, self.wh.lot_stock_id, 5, lot_id=lot)
        move = self.env['stock.move'].create({
            'name': 'Passive synthetic consumption', 'product_id': raw.id,
            'product_uom_qty': 2, 'product_uom': self.unit.id,
            'raw_material_production_id': production.id,
            'location_id': self.wh.lot_stock_id.id, 'location_dest_id': destination.id})
        move._action_confirm()
        move.move_line_ids.unlink()
        self.env['stock.move.line'].create({
            'move_id': move.id, 'product_id': raw.id, 'product_uom_id': self.unit.id,
            'quantity': 2, 'lot_id': lot.id,
            'location_id': self.wh.lot_stock_id.id, 'location_dest_id': destination.id})
        move.picked = True
        self.company.iatf_passive_enabled = False
        with self.assertRaisesRegex(UserError, '품질 보류'), self.cr.savepoint():
            move._action_done()
        self.assertNotEqual(move.state, 'done')
        self.company.iatf_passive_enabled = True
        move._action_done()
        self.assertEqual(move.state, 'done')
        self.assertTrue(lot.quality_hold)
        self.assertEqual(lot.hold_reason, 'Synthetic hold')
        self.assertTrue(self._logs(move, 'bypassed'))
        self.assertEqual(self.env['stock.quant']._get_available_quantity(
            raw, self.wh.lot_stock_id, lot_id=lot), 3)
