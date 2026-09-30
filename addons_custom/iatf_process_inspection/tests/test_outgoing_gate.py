import base64

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user
from uuid import uuid4

from .pqc_basis import PqcBasisMixin


@tagged('post_install', '-at_install')
class TestOutgoingGate(PqcBasisMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_quality_actors(cls.env.company)

    def setUp(self):
        super().setUp()
        self.unit = self.env.ref('uom.product_uom_unit')
        self.product = self.env['product.product'].create({'name': 'JIT gate bumper',
            'type': 'consu', 'is_storable': True, 'tracking': 'lot'})
        self.customer = self.env['res.partner'].create({'name': 'JIT gate customer', 'customer_rank': 1})
        self.ptype = self.env['stock.picking.type'].search([
            ('code', '=', 'outgoing'), ('company_id', '=', self.env.company.id)], limit=1)
        self.source = self.ptype.default_location_src_id
        self.customer_location = self.env.ref('stock.stock_location_customers')
        self.lots = self.env['stock.lot'].create([
            {'name': name, 'product_id': self.product.id, 'company_id': self.env.company.id}
            for name in ('JIT-GATE-A', 'JIT-GATE-B')])
        for lot in self.lots:
            self.env['stock.quant']._update_available_quantity(self.product, self.source, 5, lot_id=lot)
        self.picking = self._picking([(self.lots[0], 1), (self.lots[1], 2)])

    def _picking(self, allocations, planned=None):
        picking = self.env['stock.picking'].create({'picking_type_id': self.ptype.id,
            'partner_id': self.customer.id, 'location_id': self.source.id,
            'location_dest_id': self.customer_location.id,
            'move_ids': [Command.create({'name': self.product.name, 'product_id': self.product.id,
                'product_uom_qty': planned or sum(quantity for lot, quantity in allocations),
                'product_uom': self.unit.id, 'location_id': self.source.id,
                'location_dest_id': self.customer_location.id})]})
        picking.action_confirm()
        picking.move_ids.move_line_ids.unlink()
        for lot, quantity in allocations:
            self.env['stock.move.line'].create({'move_id': picking.move_ids.id, 'picking_id': picking.id,
                'product_id': self.product.id, 'product_uom_id': self.unit.id, 'lot_id': lot.id,
                'location_id': self.source.id, 'location_dest_id': self.customer_location.id, 'quantity': quantity})
        return picking

    def _approve(self, inspection):
        if not getattr(self, 'approver', False):
            fixture_env = self.env(context=dict(self.env.context, no_reset_password=True))
            self.approver = new_test_user(fixture_env, login='jit-quality-' + uuid4().hex,
                groups='base.group_user,stock.group_stock_user,'
                       'iatf_process_inspection.group_process_inspection_user,'
                       'iatf_shipping_inspection.group_shipping_inspection_user',
                company_id=self.env.company.id,
                company_ids=[Command.set(self.env.company.ids)])
        inspection = inspection.with_user(self.approver)
        inspection.approval_line_ids = [Command.create({'user_id': self.approver.id})]
        inspection.action_submit_approval()
        inspection.action_approve_approval()
        self.assertEqual(inspection.approval_state, 'approved')
        self.assertTrue(inspection.outgoing_approval_snapshot)

    def _release(self, picking=None):
        picking = picking or self.picking
        picking.action_prepare_oqc()
        actor = self._outgoing_actor()
        for inspection in picking.oqc_inspection_ids.filtered(lambda row: row.state == 'draft').with_user(actor):
            inspection.action_start_inspection()
            inspection.write({'inspector_id': actor.id, 'result': 'pass',
                'quantity_inspected': inspection.quantity_produced,
                'quantity_accepted': inspection.quantity_produced,
                'line_ids': [Command.create({'characteristic_name': 'Visual check',
                    'measured_value': 'OK', 'result': 'pass'})]})
            inspection.action_decide()
            self._approve(inspection)
        for inspection in picking.outgoing_shipping_inspection_ids.filtered(lambda row: row.state == 'draft').with_user(actor):
            inspection.action_start_inspection()
            inspection.write({'inspector_id': actor.id, 'result': 'pass',
                'visual_result': 'pass', 'dimension_result': 'na',
                'packaging_result': 'pass', 'label_result': 'pass'})
            inspection.action_decide()
            self._approve(inspection)
        return picking

    def test_prepare_persists_drafts_and_is_idempotent(self):
        self.picking.action_prepare_oqc()
        ids = self.picking.oqc_inspection_ids.ids
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(self.picking.outgoing_shipping_inspection_ids), 2)
        self.picking.action_prepare_oqc()
        self.assertEqual(self.picking.oqc_inspection_ids.ids, ids)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()
        self.assertEqual(self.picking.oqc_inspection_ids.ids, ids)
        self.assertEqual(self.product.qty_available, 10)

    def test_actual_count_preparation_is_not_inspection(self):
        self.picking.action_prepare_oqc()
        inspections = self.picking.oqc_inspection_ids
        self.assertEqual(sorted(inspections.mapped('quantity_produced')), [1, 2])
        self.assertEqual(inspections.mapped('quantity_inspected'), [0, 0])
        self.assertFalse(any(inspections.mapped('quantity_accepted')))

    def test_actual_count_requires_reported_quantity(self):
        self.picking.action_prepare_oqc()
        actor = self._outgoing_actor()
        inspection = self.picking.oqc_inspection_ids[:1].with_user(actor)
        inspection.action_start_inspection()
        inspection.write({'inspector_id': actor.id, 'result': 'pass',
            'quantity_accepted': inspection.quantity_produced,
            'line_ids': [Command.create({'characteristic_name': 'SYNTHETIC observation',
                'measured_value': 'SYNTHETIC OK', 'result': 'pass'})]})
        with self.assertRaises(UserError):
            inspection.action_decide()
        self.assertFalse(inspection.outgoing_decision_snapshot)

    def test_actual_count_closed_outgoing_cancel_visible(self):
        from lxml import etree
        from odoo.tools.safe_eval import safe_eval
        self._release()
        for record, xmlid in (
                (self.picking.oqc_inspection_ids[:1], 'iatf_process_inspection.view_process_inspection_form'),
                (self.picking.outgoing_shipping_inspection_ids[:1], 'iatf_shipping_inspection.view_shipping_inspection_form')):
            record.action_close()
            self.assertEqual(record.state, 'closed')
            view = record.with_user(self.decision_actor).get_view(self.env.ref(xmlid).id, 'form')
            button = etree.fromstring(view['arch']).xpath('//header/button[@name="action_cancel"]')[0]
            invisible = safe_eval(button.get('invisible', 'False'), {'state': 'closed', 'inspection_stage': 'oqc',
                'picking_id': self.picking.id, 'outgoing_can_cancel': True})
            self.assertFalse(invisible, '미출고 상태의 종료 검사를 원본 보존 후 정정할 수 있어야 한다')

    def test_actual_count_repreparing_preserves_actual_report(self):
        self.picking.action_prepare_oqc()
        inspection = self.picking.oqc_inspection_ids[:1].with_user(self._outgoing_actor())
        inspection.action_start_inspection()
        inspection.quantity_inspected = 1
        original_ids = self.picking.oqc_inspection_ids.ids
        self.picking.action_prepare_oqc()
        self.assertEqual(self.picking.oqc_inspection_ids.ids, original_ids)
        self.assertEqual(inspection.quantity_inspected, 1)
        self.assertEqual(sum(self.picking.oqc_inspection_ids.mapped('quantity_produced')), 3)

    def test_actual_count_partial_report_cannot_release_full_shipment(self):
        self.picking.action_prepare_oqc()
        inspection = self.picking.oqc_inspection_ids.filtered(lambda row: row.quantity_produced == 2).with_user(self._outgoing_actor())
        inspection.action_start_inspection()
        inspection.write({'inspector_id': inspection.env.uid, 'result': 'pass',
            'quantity_inspected': 1, 'quantity_accepted': 1,
            'line_ids': [Command.create({'characteristic_name': 'SYNTHETIC only one unit inspected',
                'measured_value': 'SYNTHETIC OK for one unit', 'result': 'pass'})]})
        inspection.action_decide()
        with self.assertRaises(UserError):
            self._approve(inspection)
        self.assertEqual(inspection.quantity_inspected, 1)
        self.assertEqual(self.product.qty_available, 10)

    def test_actual_count_closed_correction_and_posted_lock(self):
        self._release()
        originals = []
        for rows in (self.picking.oqc_inspection_ids, self.picking.outgoing_shipping_inspection_ids):
            for record in rows.with_user(self.decision_actor):
                originals.append((record, dict(record.outgoing_decision_snapshot),
                    dict(record.outgoing_approval_snapshot), record.approval_request_id))
                record.action_close()
                self.assertTrue(record.outgoing_can_cancel)
                record.action_cancel()
                self.assertFalse(record.outgoing_can_cancel)
        self.picking.action_prepare_oqc()
        self.assertEqual(self.picking.oqc_inspection_ids.filtered(lambda row: row.state == 'draft').mapped('quantity_inspected'), [0, 0])
        self._release()
        self.picking.button_validate()
        self.assertEqual(self.product.qty_available, 7)
        for record, decision, approval, request in originals:
            self.assertEqual(record.state, 'cancelled')
            self.assertEqual(record.outgoing_decision_snapshot, decision)
            self.assertEqual(record.outgoing_approval_snapshot, approval)
            self.assertEqual(request.state, 'approved')
        for rows in (self.picking.oqc_inspection_ids, self.picking.outgoing_shipping_inspection_ids):
            for record in rows.filtered(lambda row: row.state != 'cancelled'):
                self.assertFalse(record.outgoing_can_cancel)
                with self.assertRaises(UserError):
                    record.action_cancel()

    def _outgoing_actor(self):
        if not getattr(self, 'decision_actor', False):
            self.decision_actor = new_test_user(self.env(context=dict(self.env.context, no_reset_password=True)),
                login='outgoing-decision-' + uuid4().hex,
                groups='base.group_user,stock.group_stock_user,'
                       'iatf_process_inspection.group_process_inspection_user,'
                       'iatf_shipping_inspection.group_shipping_inspection_user,'
                       'iatf_nonconformity.group_nc_user',
                company_id=self.env.company.id, company_ids=[Command.set(self.env.company.ids)])
        return self.decision_actor

    def _decision_fixture(self, packaging=False, forged=False):
        self.picking.action_prepare_oqc()
        actor = self._outgoing_actor()
        record = (self.picking.outgoing_shipping_inspection_ids if packaging else
                  self.picking.oqc_inspection_ids)[:1].with_user(actor)
        record.action_start_inspection()
        values = {'inspector_id': actor.id, 'result': 'pass'}
        if packaging:
            values.update(visual_result='pass', dimension_result='na', packaging_result='pass', label_result='pass')
        else:
            values.update(quantity_inspected=record.quantity_produced, quantity_accepted=record.quantity_produced,
                line_ids=[Command.create({'characteristic_name': 'SYNTHETIC visual',
                    'measured_value': 'SYNTHETIC OK', 'result': 'pass'})])
        record.write(values)
        # Common approval creates an empty draft request when the record is
        # created. That is not historical submission and must not block judging.
        self.assertEqual(record.approval_request_id.state, 'draft')
        if forged:
            # Deliberately fabricated legacy state: this is a negative fixture.
            record.write({'state': 'decided'})
        return record

    def test_decision_oqc_without_actual_action_cannot_submit(self):
        record = self._decision_fixture(forged=True)
        with self.assertRaises(UserError):
            self._approve(record)

    def test_decision_packaging_without_actual_action_cannot_submit(self):
        record = self._decision_fixture(packaging=True, forged=True)
        with self.assertRaises(UserError):
            self._approve(record)

    def test_decision_another_inspector_cannot_decide(self):
        record = self._decision_fixture()
        with self.assertRaises(UserError):
            record.with_user(self.env.user).action_decide()

    def test_decision_inspector_cannot_approve_own_result(self):
        record = self._decision_fixture()
        record.action_decide()
        record.approval_line_ids = [Command.create({'user_id': record.env.uid})]
        with self.assertRaises(UserError):
            record.action_submit_approval()
            record.action_approve_approval()

    def test_decision_actual_records_and_repeat_preserve_approval(self):
        self._release()
        for records in (self.picking.oqc_inspection_ids, self.picking.outgoing_shipping_inspection_ids):
            for record in records.with_user(self.decision_actor):
                decision = dict(record.outgoing_decision_snapshot)
                request = record.approval_request_id
                self.assertEqual(record.outgoing_decided_by_id, self.decision_actor)
                self.assertTrue(record.outgoing_decided_at)
                record.action_decide()
                self.assertEqual(record.outgoing_decision_snapshot, decision)
                self.assertEqual(record.approval_request_id, request)
                self.assertEqual(record.approval_state, 'approved')
        self.picking.button_validate()
        self.assertEqual(self.product.qty_available, 7)

    def test_decision_missing_inspector_blocks(self):
        for packaging in (False, True):
            record = self._decision_fixture(packaging=packaging)
            record.inspector_id = False
            with self.assertRaises(UserError):
                record.action_decide()
            self.assertFalse(record.outgoing_decision_snapshot)

    def test_decision_packaging_other_inspector_and_self_approval_blocked(self):
        record = self._decision_fixture(packaging=True)
        with self.assertRaises(UserError):
            record.with_user(self.env.user).action_decide()
        record.action_decide()
        record.approval_line_ids = [Command.create({'user_id': record.env.uid})]
        with self.assertRaises(UserError):
            record.action_submit_approval()

    def test_decision_fields_and_context_cannot_be_forged(self):
        for packaging in (False, True):
            record = self._decision_fixture(packaging=packaging)
            for key, value in (('outgoing_decision_snapshot', {'forged': True}),
                    ('outgoing_decided_by_id', record.env.uid), ('outgoing_decided_at', '2026-01-01 00:00:00')):
                with self.assertRaises(UserError):
                    record.write({key: value})
                with self.assertRaises(UserError):
                    record.with_context(**{'default_' + key: value}).create({
                        'product_id': self.product.id, 'picking_id': self.picking.id})

    def test_decision_packaging_result_identity_and_notes_are_immutable(self):
        record = self._decision_fixture(packaging=True)
        record.action_decide()
        decision = dict(record.outgoing_decision_snapshot)
        for values in ({'result': 'fail'}, {'label_result': 'fail'}, {'quantity': 10},
                {'inspector_id': self.env.uid}, {'notes': 'Changed inspected result'},
                {'shipping_date': '2026-01-01'}, {'state': 'inspecting'}):
            with self.assertRaises(UserError):
                record.write(values)
            self.assertEqual(record.outgoing_decision_snapshot, decision)
        self._approve(record)

    def test_decision_cancel_and_new_inspection_preserve_original(self):
        self._release()
        old = self.picking.oqc_inspection_ids[:1]
        decision, approval = dict(old.outgoing_decision_snapshot), dict(old.outgoing_approval_snapshot)
        old.action_cancel()
        with self.assertRaises(UserError):
            old.write({'state': 'decided'})
        with self.assertRaises(UserError):
            old.unlink()
        self.picking.action_prepare_oqc()
        new = self.picking.oqc_inspection_ids.filtered(lambda row: row.state == 'draft').with_user(self.decision_actor)
        self.assertEqual(len(new), 1)
        new.action_start_inspection()
        new.write({'inspector_id': self.decision_actor.id, 'result': 'pass',
            'quantity_inspected': new.quantity_produced, 'quantity_accepted': new.quantity_produced,
            'line_ids': [Command.create({'characteristic_name': 'SYNTHETIC reinspection',
                'measured_value': 'SYNTHETIC OK', 'result': 'pass'})]})
        new.action_decide()
        self._approve(new)
        self.picking.button_validate()
        self.assertEqual(self.picking.state, 'done')
        self.assertEqual(old.outgoing_decision_snapshot, decision)
        self.assertEqual(old.outgoing_approval_snapshot, approval)
        self.assertNotEqual(new.outgoing_decision_snapshot['id'], old.id)

    def test_decision_packaging_nonfinite_or_missing_result_blocked(self):
        record = self._decision_fixture(packaging=True)
        quantity = record.quantity
        for values in ({'quantity': float('nan')}, {'quantity': float('inf')}, {'quantity': 0}, {'label_result': False}):
            record.write({'quantity': quantity, 'label_result': 'pass', **values})
            with self.assertRaises(UserError):
                record.action_decide()
            self.assertFalse(record.outgoing_decision_snapshot)

    def test_decision_views_resolve(self):
        for model, xmlid in (
                ('iatf.process.inspection', 'iatf_process_inspection.view_process_inspection_form'),
                ('iatf.shipping.inspection', 'iatf_shipping_inspection.view_shipping_inspection_form')):
            view = self.env[model].with_user(self._outgoing_actor()).get_view(self.env.ref(xmlid).id, 'form')
            self.assertIn('outgoing_decided_by_id', view['arch'])
            self.assertIn('outgoing_decided_at', view['arch'])

    def test_decision_legacy_history_is_not_backfilled(self):
        for packaging in (False, True):
            record = self._decision_fixture(packaging=packaging)
            record.action_decide()
            self._approve(record)
            approval = dict(record.outgoing_approval_snapshot)
            # Negative legacy fixture only: previous releases had no such field.
            record.flush_recordset()
            from odoo.tools import SQL
            self.cr.execute(SQL('UPDATE %s SET outgoing_decision_snapshot=NULL WHERE id=%s',
                SQL.identifier(record._table), record.id))
            record.invalidate_recordset()
            record.action_reset_approval()
            record.write({'state': 'inspecting'})
            with self.assertRaises(UserError):
                record.action_decide()
            self.assertFalse(record.outgoing_decision_snapshot)
            self.assertEqual(record.outgoing_approval_snapshot, approval)

    def test_validation_does_not_create_unsaved_inspections(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()
        self.assertFalse(self.picking.oqc_inspection_ids)

    def test_supplier_destination_alone_does_not_bypass_inspection(self):
        supplier_location = self.env.ref('stock.stock_location_suppliers')
        self.picking.location_dest_id = supplier_location
        self.picking.move_ids.location_dest_id = supplier_location
        self.picking.move_ids.move_line_ids.location_dest_id = supplier_location
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()
        self.assertNotEqual(self.picking.state, 'done')
        self.assertEqual(self.product.qty_available, 10)

    def test_approved_two_lots_ship_exact_quantities_and_retry(self):
        self._release()
        self.picking.button_validate()
        self.assertEqual(self.picking.state, 'done')
        self.assertEqual(self.product.qty_available, 7)
        self.picking.button_validate()
        self.assertEqual(self.product.qty_available, 7)

    def _outgoing_evidence_file(self, packaging=False, approve=True):
        self._release()
        inspection = (self.picking.outgoing_shipping_inspection_ids if packaging else self.picking.oqc_inspection_ids)[:1]
        inspection.action_reset_approval()
        attachment = self.env['ir.attachment'].create({'name': 'SYNTHETIC shipping evidence.txt',
            'datas': base64.b64encode(b'ORIGINAL SHIPPING EVIDENCE'),
            'res_model': inspection._name, 'res_id': inspection.id})
        inspection.write({'attachment_ids': [Command.link(attachment.id)]})
        inspection = inspection.with_user(self.approver)
        inspection.approval_line_ids = [Command.clear(), Command.create({'user_id': self.approver.id})]
        inspection.action_submit_approval()
        if approve:
            inspection.action_approve_approval()
        return inspection, attachment

    def test_changed_oqc_file_cannot_ship(self):
        inspection, attachment = self._outgoing_evidence_file()
        attachment.write({'datas': base64.b64encode(b'CHANGED AFTER APPROVAL')})
        with self.assertRaises(UserError):
            self.picking.button_validate()
        self.assertNotEqual(self.picking.state, 'done')

    def test_changed_packaging_file_cannot_ship(self):
        inspection, attachment = self._outgoing_evidence_file(packaging=True)
        attachment.write({'datas': base64.b64encode(b'CHANGED AFTER APPROVAL')})
        with self.assertRaises(UserError):
            self.picking.button_validate()
        self.assertNotEqual(self.picking.state, 'done')

    def test_changed_outgoing_file_cannot_be_signed(self):
        inspection, attachment = self._outgoing_evidence_file(approve=False)
        attachment.write({'datas': base64.b64encode(b'CHANGED WHILE WAITING FOR SIGNATURE')})
        with self.assertRaises(UserError):
            inspection.action_approve_approval()

    def test_unchanged_outgoing_file_ships(self):
        inspection, attachment = self._outgoing_evidence_file()
        self.assertEqual(inspection.outgoing_approval_snapshot['linked_evidence']['attachments'][0]['checksum'], attachment.checksum)
        self.picking.button_validate()
        self.assertEqual(self.picking.state, 'done')
        self.assertEqual(self.product.qty_available, 7)

    def test_deleted_outgoing_file_cannot_ship(self):
        inspection, attachment = self._outgoing_evidence_file()
        attachment.unlink()
        with self.assertRaises(UserError):
            self.picking.button_validate()
        self.assertNotEqual(self.picking.state, 'done')

    def test_old_file_scope_is_not_backfilled_during_stock_validation(self):
        inspection, attachment = self._outgoing_evidence_file()
        original = dict(inspection.outgoing_approval_snapshot)
        old = dict(original)
        old.pop('linked_evidence')
        # Deliberate legacy fixture only; never a successful business path.
        inspection.flush_recordset()
        from psycopg2.extras import Json
        self.cr.execute('UPDATE iatf_process_inspection SET outgoing_approval_snapshot=%s WHERE id=%s', (Json(old), inspection.id))
        inspection.invalidate_recordset()
        with self.assertRaises(UserError):
            self.picking.button_validate()
        self.assertEqual(inspection.outgoing_approval_snapshot, old)

    def test_hold_oqc_blocks_shipping(self):
        record = self._decision_fixture()
        record.result = 'hold'
        record.action_decide()
        with self.assertRaises(UserError):
            self._approve(record)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()
        self.assertEqual(self.product.qty_available, 10)

    def test_unapproved_direct_pass_blocks_shipping(self):
        self.picking.action_prepare_oqc()
        self.picking.oqc_inspection_ids.write({'state': 'decided', 'result': 'pass'})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()

    def test_conditional_without_concession_is_blocked(self):
        inspection = self._decision_fixture()
        inspection.result = 'conditional'
        inspection.action_decide()
        with self.assertRaises(UserError):
            inspection.action_submit_approval()

    def test_held_lot_after_approval_blocks_stock_boundary(self):
        self._release()
        self.lots[0].quality_hold = True
        self.picking.move_ids.picked = True
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.move_ids._action_done()
        self.assertEqual(self.product.qty_available, 10)

    def test_missing_lot_coverage_blocks(self):
        self._release()
        self.picking.oqc_inspection_ids[:1].state = 'cancelled'
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()

    def test_quantity_change_after_approval_blocks(self):
        self._release()
        self.picking.move_ids.move_line_ids[:1].quantity = 2
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()

    def test_decided_measurement_change_is_rejected(self):
        self._release()
        inspection = self.picking.oqc_inspection_ids[:1]
        original = dict(inspection.outgoing_approval_snapshot)
        with self.assertRaises(UserError):
            inspection.line_ids.measured_value = 'CHANGED'
        self.assertEqual(inspection.line_ids.measured_value, 'OK')
        self.assertEqual(inspection.approval_state, 'approved')
        self.assertEqual(inspection.outgoing_approval_snapshot, original)

    def test_empty_measurements_cannot_be_submitted(self):
        self.picking.action_prepare_oqc()
        inspection = self.picking.oqc_inspection_ids[:1]
        inspection.write({'state': 'decided', 'result': 'pass', 'quantity_accepted': inspection.quantity_inspected})
        with self.assertRaises(UserError):
            inspection.action_submit_approval()

    def test_packaging_or_label_fail_blocks(self):
        record = self._decision_fixture(packaging=True)
        record.label_result = 'fail'
        with self.assertRaises(UserError):
            record.action_decide()
        record.result = 'fail'
        record.action_decide()
        self.assertTrue(record.nonconformity_id)
        with self.assertRaises(UserError):
            self._approve(record)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()

    def test_foreign_inspection_company_is_rejected(self):
        other = self.env['res.company'].create({'name': 'JIT other company'})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['iatf.process.inspection'].create({'inspection_stage': 'oqc',
                'picking_id': self.picking.id, 'product_id': self.product.id, 'company_id': other.id,
                'quantity_inspected': 1})

    def test_stock_user_can_prepare_read_and_ship_without_quality_edit(self):
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'JIT stock operator', 'login': 'jit-stock-operator',
            'company_id': self.env.company.id, 'company_ids': [Command.set([self.env.company.id])],
            'groups_id': [Command.set([self.env.ref('stock.group_stock_user').id])]})
        self.picking.with_user(user).action_prepare_oqc()
        self.assertEqual(len(self.picking.with_user(user).oqc_inspection_ids), 2)
        with self.assertRaises(AccessError):
            self.picking.oqc_inspection_ids.with_user(user).write({'result': 'pass'})
        self._release()
        self.picking.with_user(user).button_validate()
        self.assertEqual(self.picking.state, 'done')

    def test_completed_inspection_and_measurements_are_immutable(self):
        self._release()
        self.picking.button_validate()
        inspection = self.picking.oqc_inspection_ids[:1]
        with self.assertRaises(UserError):
            inspection.write({'result': 'fail'})
        with self.assertRaises(UserError):
            inspection.line_ids.write({'measured_value': 'CHANGED'})
        with self.assertRaises(UserError):
            inspection.unlink()

    def test_private_stock_completion_cannot_bypass_inspection(self):
        self.picking.move_ids.picked = True
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.move_ids._action_done()

    def test_direct_snapshot_forgery_is_rejected(self):
        self.picking.action_prepare_oqc()
        with self.assertRaises(UserError):
            self.picking.oqc_inspection_ids.write({'outgoing_approval_snapshot': {'forged': True}})

    def test_trace_uses_move_line_quantities_and_source_links(self):
        if 'move_line_id' not in self.env['iatf.traceability.record']._fields:
            self.skipTest('Install iatf_traceability for source-link assertions')
        self._release()
        self.picking.button_validate()
        trace = self.env['iatf.traceability.record'].search([('picking_id', '=', self.picking.id)])
        self.assertEqual(len(trace), 2)
        self.assertEqual(sorted(trace.mapped('quantity')), [1, 2])
        self.assertEqual(trace.partner_id, self.customer)
        self.assertEqual(trace.move_line_id, self.picking.move_ids.move_line_ids)
        self.picking.move_ids._create_traceability_record()
        self.assertEqual(self.env['iatf.traceability.record'].search_count([('picking_id', '=', self.picking.id)]), 2)
        with self.assertRaises(UserError):
            trace.write({'quantity': 10})

    def test_move_dozen_uom_is_checked_in_product_stock_units(self):
        self.picking.move_ids.write({'product_uom': self.env.ref('uom.product_uom_dozen').id,
                                     'product_uom_qty': 0.25})
        # Core intentionally unreserves on UOM change; re-enter actual LOT detail.
        for lot, quantity in ((self.lots[0], 1), (self.lots[1], 2)):
            self.env['stock.move.line'].create({'move_id': self.picking.move_ids.id,
                'picking_id': self.picking.id, 'product_id': self.product.id,
                'product_uom_id': self.unit.id, 'lot_id': lot.id, 'quantity': quantity,
                'location_id': self.source.id, 'location_dest_id': self.customer_location.id})
        self._release()
        self.picking.button_validate()
        self.assertEqual(self.picking.state, 'done')
        self.assertEqual(self.product.qty_available, 7)

    def test_partial_delivery_backorder_requires_its_own_approval(self):
        self.picking.move_ids.product_uom_qty = 4
        self._release()
        self.picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(self.picking.state, 'done')
        backorder = self.env['stock.picking'].search([('backorder_id', '=', self.picking.id)])
        self.assertEqual(len(backorder), 1)
        self.assertFalse(backorder.oqc_inspection_ids)
        self.assertFalse(backorder.outgoing_shipping_inspection_ids)
        with self.assertRaises(UserError), self.cr.savepoint():
            backorder.button_validate()

    def test_customer_change_after_approval_invalidates_scope(self):
        self._release()
        other = self.env['res.partner'].create({'name': 'Other customer'})
        self.picking.partner_id = other
        with self.assertRaises(UserError), self.cr.savepoint():
            self.picking.button_validate()

    def test_company_record_rule_hides_foreign_inspection(self):
        self.picking.action_prepare_oqc()
        other = self.env['res.company'].create({'name': 'Foreign company'})
        user = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Foreign quality user', 'login': 'foreign-quality-user',
            'company_id': other.id, 'company_ids': [Command.set([other.id])],
            'groups_id': [Command.set([self.env.ref('iatf_process_inspection.group_process_inspection_user').id])]})
        self.assertEqual(self.env['iatf.process.inspection'].with_user(user).search_count([
            ('id', 'in', self.picking.oqc_inspection_ids.ids)]), 0)

    def test_actual_assembly_good_output_ships_once_and_duplicate_is_blocked(self):
        if 'is_jr' not in self.env['mrp.production']._fields:
            self.skipTest('Install gh_total_mes for actual assembly output')
        raw = self.env['product.product'].create({'name': 'JIT real assembly component',
            'type': 'consu', 'is_storable': True, 'tracking': 'lot'})
        raw_lot = self.env['stock.lot'].create({'name': 'JIT-ASSEMBLY-RAW',
            'product_id': raw.id, 'company_id': self.env.company.id})
        self.env['stock.quant']._update_available_quantity(raw, self.source, 2, lot_id=raw_lot)
        wc = self.env['mrp.workcenter'].create({'name': 'JIT actual assembly', 'is_jr': True})
        bom = self.env['mrp.bom'].create({'product_tmpl_id': self.product.product_tmpl_id.id,
            'product_id': self.product.id, 'product_qty': 1, 'product_uom_id': self.unit.id,
            'operation_ids': [Command.create({'name': 'JIT fit', 'workcenter_id': wc.id})]})
        self.env['mrp.bom.line'].create({'bom_id': bom.id, 'product_id': raw.id,
            'product_qty': 2, 'product_uom_id': self.unit.id, 'operation_id': bom.operation_ids.id})
        mo = self.env['mrp.production'].create({'product_id': self.product.id, 'product_qty': 1,
            'product_uom_id': self.unit.id, 'bom_id': bom.id, 'is_jr': True})
        mo.action_confirm()
        check = self.env['ej.check.model'].make(mo.workorder_ids[:1], False)
        for _ in range(2):
            self.assertTrue(check.add_scan(raw_lot.name, wc)[0])
        self.assertTrue(check.commit())
        mo.qty_producing = 1
        # 합본에서는 완료에 **승인 관리계획과 필요 검사**가 있어야 한다. 게이트를
        # 낮추지 않고 정상 절차로 갖춘다(단독 설치에서는 아무 일도 하지 않는다).
        # 검사 준비는 **실제 생산 LOT** 를 먼저 요구한다.
        if mo.product_id.tracking != 'none' and not mo.lot_producing_id:
            mo.lot_producing_id = self.env['stock.lot'].create({
                'name': 'JIT-GATE-%s' % mo.id, 'product_id': mo.product_id.id,
                'company_id': mo.company_id.id}).id
        self._ensure_quality_basis(mo)
        mo._process_shipping_qc(True)
        self.assertEqual(mo.state, 'done')
        self.assertEqual(mo.mes_confirmed_good_qty, 1)
        self.assertEqual(self.product.qty_available, 11)
        first = self._picking([(mo.lot_producing_id, 1)])
        self._release(first)
        first.button_validate()
        self.assertEqual(first.state, 'done')
        self.assertEqual(self.product.qty_available, 10)
        second = self._picking([(mo.lot_producing_id, 1)])
        self._release(second)
        with self.assertRaisesRegex(UserError, '실재고'), self.cr.savepoint():
            second.button_validate()
        self.assertNotEqual(second.state, 'done')
        self.assertEqual(self.product.qty_available, 10)

    def test_posted_stock_evidence_and_direct_done_cannot_bypass_gate(self):
        with self.assertRaises(UserError):
            self.picking.write({'state': 'done'})
        with self.assertRaises(UserError):
            self.picking.move_ids.write({'state': 'done'})
        self._release()
        self.picking.button_validate()
        for vals in ({'partner_id': False}, {'picking_type_id': self.env.ref('stock.picking_type_internal').id},
                     {'state': 'draft'}, {'origin': 'retroactive customer order'}):
            with self.assertRaises(UserError):
                self.picking.write(vals)
        with self.assertRaises(UserError):
            self.picking.move_ids.write({'quantity': 20})
        with self.assertRaises(UserError):
            self.picking.move_ids.move_line_ids[:1].write({'quantity': 20})
        with self.assertRaises(UserError):
            self.picking.move_ids.move_line_ids[:1].unlink()
        self.assertEqual(self.product.qty_available, 7)
        trace = self.env['iatf.traceability.record'].search([('picking_id', '=', self.picking.id)])
        with self.assertRaises(UserError):
            trace.write({'picking_id': False})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['iatf.traceability.record'].with_context(default_picking_id=self.picking.id).create({
                'product_id': self.product.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['iatf.process.inspection'].with_context(default_picking_id=self.picking.id).create({
                'product_id': self.product.id, 'inspection_stage': 'oqc', 'quantity_inspected': 1})

    def test_missing_customer_is_blocked(self):
        self.picking.partner_id = False
        with self.assertRaises(UserError):
            self.picking.action_prepare_oqc()

    def test_context_defaults_cannot_forge_snapshot_or_posted_measurement(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['iatf.process.inspection'].with_context(
                default_outgoing_approval_snapshot={'forged': True}).create({
                    'product_id': self.product.id, 'picking_id': self.picking.id,
                    'inspection_stage': 'oqc', 'quantity_inspected': 1})
        self._release()
        self.picking.button_validate()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['iatf.process.inspection.line'].with_context(
                default_inspection_id=self.picking.oqc_inspection_ids[:1].id).create({
                    'characteristic_name': 'Late inserted evidence', 'measured_value': 'OK', 'result': 'pass'})


def run_outgoing_concurrency_probe(env):
    """Two real transactions; explicitly restricted to the disposable JIT DB."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event
    from uuid import uuid4

    from psycopg2.errors import SerializationFailure
    from odoo import api, sql_db, SUPERUSER_ID

    assert env.cr.dbname == 'cams_night_materials_jit_gate'
    marker = 'JIT-CONCURRENT-' + uuid4().hex[:8]

    class Fixture:
        _picking = TestOutgoingGate._picking
        _approve = TestOutgoingGate._approve
        _release = TestOutgoingGate._release

        def assertEqual(self, first, second):
            assert first == second, (first, second)

        def assertTrue(self, value):
            assert value

    fixture = Fixture()
    fixture.env = env
    fixture.unit = env.ref('uom.product_uom_unit')
    fixture.ptype = env['stock.picking.type'].search([
        ('code', '=', 'outgoing'), ('company_id', '=', env.company.id)], limit=1)
    fixture.source = fixture.ptype.default_location_src_id
    fixture.customer_location = env.ref('stock.stock_location_customers')
    fixture.customer = env['res.partner'].create({'name': marker + '-customer', 'customer_rank': 1})

    def stock_product(label):
        fixture.product = env['product.product'].create({'name': marker + label,
            'type': 'consu', 'is_storable': True, 'tracking': 'lot'})
        # Scope classifier only; actual completed assembly is separately covered
        # by test_actual_assembly_good_output_ships_once_and_duplicate_is_blocked.
        env['mrp.production'].create({'product_id': fixture.product.id, 'product_qty': 1,
            'product_uom_id': fixture.unit.id, 'is_jr': True})
        lot = env['stock.lot'].create({'name': marker + label, 'product_id': fixture.product.id,
                                     'company_id': env.company.id})
        env['stock.quant']._update_available_quantity(fixture.product, fixture.source, 1, lot_id=lot)
        return lot

    def race(pickings):
        barrier = Barrier(2)
        dbname = env.cr.dbname

        def worker(picking_id):
            for attempt in range(4):
                try:
                    with sql_db.db_connect(dbname).cursor() as cr:
                        other = api.Environment(cr, SUPERUSER_ID, {})
                        cr.execute('SELECT id FROM stock_picking WHERE id = %s', [picking_id])
                        if not attempt:
                            barrier.wait(timeout=15)
                        picking = other['stock.picking'].browse(picking_id)
                        picking.button_validate()
                        state = picking.state
                        cr.commit()
                        return {'ok': state == 'done', 'retries': attempt}
                except SerializationFailure:
                    if attempt == 3:
                        raise
                except UserError as exc:
                    return {'ok': False, 'retries': attempt, 'error': str(exc)}
            raise AssertionError('Retry exhaustion')

        env.cr.commit()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, picking.id) for picking in pickings]
            result = [future.result(timeout=45) for future in futures]
        env.cr.rollback()
        env.invalidate_all()
        return result

    lot = stock_product('-same-picking')
    fixture.picking = fixture._picking([(lot, 1)])
    fixture._release()
    duplicate_request = race([fixture.picking, fixture.picking])
    assert all(result['ok'] for result in duplicate_request)
    assert sum(result['retries'] for result in duplicate_request) >= 1
    assert fixture.product.qty_available == 0
    assert len(env['iatf.traceability.record'].search([('picking_id', '=', fixture.picking.id)])) == 1

    lot = stock_product('-competing-pickings')
    first = fixture._picking([(lot, 1)])
    second = fixture._picking([(lot, 1)])
    fixture._release(first)
    fixture._release(second)
    competing = race([first, second])
    assert sum(result['ok'] for result in competing) <= 1
    assert not all(result['ok'] for result in competing)
    assert fixture.product.qty_available >= 0
    competing_stock = fixture.product.qty_available

    def scope_race(first_action):
        lot = stock_product('-scope-' + first_action)
        picking = fixture._release(fixture._picking([(lot, 1)]))
        picking_id, lot_id = picking.id, lot.id
        line_id = picking.oqc_inspection_ids.line_ids[:1].id
        env.cr.commit()
        locked, second_read = Event(), Event()

        def worker(first):
            for attempt in range(4):
                try:
                    with sql_db.db_connect(env.cr.dbname).cursor() as cr:
                        other = api.Environment(cr, SUPERUSER_ID, {})
                        row = other['stock.picking'].browse(picking_id)
                        if first:
                            if first_action == 'ship':
                                row._lock_outgoing()
                                row._assert_outgoing_inspections()
                            else:
                                other['stock.lot'].browse(lot_id).write({'quality_hold': True})
                            locked.set()
                            assert second_read.wait(15)
                            if first_action == 'ship':
                                row.button_validate()
                        else:
                            assert locked.wait(15)
                            row.read(['state'])  # Pin a snapshot before the first commit.
                            second_read.set()
                            if first_action == 'ship':
                                other['iatf.process.inspection.line'].browse(line_id).write({'result': 'fail'})
                            else:
                                row.button_validate()
                        cr.commit()
                        return {'ok': True, 'retries': attempt}
                except SerializationFailure:
                    if attempt == 3:
                        raise
                except UserError as exc:
                    return {'ok': False, 'retries': attempt, 'error': str(exc)}
            raise AssertionError('Retry exhaustion')

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, first) for first in (True, False)]
            result = [future.result(timeout=45) for future in futures]
        env.cr.rollback()
        env.invalidate_all()
        assert result[0]['ok'] and not result[1]['ok'], result
        assert result[1]['retries'] >= 1, result
        assert picking.state == ('done' if first_action == 'ship' else 'assigned'), picking.state
        assert fixture.product.qty_available == (0 if first_action == 'ship' else 1)
        return result

    shipment_then_measurement = scope_race('ship')
    hold_then_shipment = scope_race('hold')
    return {'marker': marker, 'same_picking': duplicate_request, 'competing_pickings': competing,
            'remaining_stock': competing_stock, 'shipment_then_measurement': shipment_then_measurement,
            'hold_then_shipment': hold_then_shipment, 'status': 'PASS'}
