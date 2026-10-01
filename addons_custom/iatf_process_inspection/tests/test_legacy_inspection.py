"""Upgrade-era forms must allow real inputs without changing historical evidence."""
from copy import deepcopy
from freezegun import freeze_time

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user

from ..models.process_inspection import _AUTO_EVIDENCE_TOKEN
from .pqc_basis import PqcBasisMixin


@tagged('post_install', '-at_install')
class TestLegacyInspection(PqcBasisMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls._setup_quality_actors(cls.company)
        cls.product = cls.env['product.product'].create({'name': 'SYNTHETIC legacy inspection'})
        cls.PQC = cls.env['iatf.process.inspection']
        cls.operator = new_test_user(
            cls.env(context=dict(cls.env.context, no_reset_password=True)),
            login='synthetic-legacy-inspector', groups='base.group_user,iatf_process_inspection.group_process_inspection_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])

    def _draft(self, **values):
        rec = self.PQC.with_context(_process_auto_evidence_token=_AUTO_EVIDENCE_TOKEN).create(dict({
            'company_id': self.company.id, 'product_id': self.product.id,
            'inspection_stage': 'ipqc', 'quantity_produced': 2,
            'quantity_inspected': 0, 'run_unit_mo_ids': [100001, 100002],
        }, **values))
        return self.PQC.browse(rec.id).with_user(self.operator)

    def _measure(self, rec):
        rec.write({'quantity_inspected': 1, 'quantity_accepted': 1, 'result': 'pass',
                   'inspector_id': self.operator.id,
                   'line_ids': [Command.create({'characteristic_name': 'Visual',
                       'characteristic_type': 'visual', 'measured_value': 'SYNTHETIC observed', 'result': 'pass'})]})

    def test_old_run_draft_accepts_measurements_and_decides(self):
        rec = self._draft()
        self.assertTrue(rec._run_can_accumulate())
        rec.action_start_inspection()
        self.assertTrue(rec.run_scope_frozen)
        self._measure(rec)
        rec.action_decide()
        self.assertEqual(rec.state, 'decided')
        self.assertTrue(rec.auto_evidence_snapshot)
        self.assertEqual(rec.quantity_produced, 2)
        self.assertEqual(rec.run_unit_mo_ids, [100001, 100002])
        for values in ({'quantity_inspected': 2}, {'state': 'draft'}, {'run_scope_frozen': False}):
            with self.assertRaises(UserError), self.cr.savepoint():
                rec.write(values)
        with self.assertRaises(UserError), self.cr.savepoint():
            rec.line_ids.write({'measured_value': 'changed'})

    def test_measurement_before_start_freezes_but_scope_stays_read_only(self):
        rec = self._draft()
        self._measure(rec)
        self.assertTrue(rec.run_scope_frozen)
        self.assertFalse(rec._run_can_accumulate())
        with self.assertRaises(UserError), self.cr.savepoint():
            rec.write({'quantity_produced': 9})
        with self.assertRaises(UserError), self.cr.savepoint():
            rec.write({'quantity_uom_id': self.env.ref('uom.product_uom_dozen').id})
        rec.write({'quantity_produced': 2})  # Old clients may echo unchanged scope.

    def test_direct_line_input_and_parent_reassignment_obey_locks(self):
        rec = self._draft()
        line = self.env['iatf.process.inspection.line'].with_user(self.operator).create({
            'inspection_id': rec.id, 'characteristic_name': 'Visual'})
        self.assertFalse(rec.run_scope_frozen)
        line.write({'measured_value': 'observed', 'result': 'pass'})
        self.assertTrue(rec.run_scope_frozen)
        other = self._draft(state='decided')  # Historical document without a snapshot.
        with self.assertRaises(UserError), self.cr.savepoint():
            line.write({'inspection_id': other.id})

    def test_legacy_decided_without_snapshot_is_not_reopened(self):
        rec = self._draft(state='decided')
        self.assertFalse(rec.auto_evidence_snapshot)
        self.assertTrue(rec.inspection_input_locked)
        with self.assertRaises(UserError), self.cr.savepoint():
            rec.write({'quantity_inspected': 1})
        with self.assertRaises(UserError), self.cr.savepoint():
            rec.action_start_inspection()

    def test_reinspection_keeps_original_and_needs_new_evidence(self):
        rec = self._draft()
        self._measure(rec)
        rec.action_decide()
        original = deepcopy(rec.auto_evidence_snapshot)
        action = rec.action_create_reinspection()
        new = self.PQC.browse(action['res_id']).with_user(self.operator)
        self.assertEqual(new.correction_of_id, rec)
        self.assertEqual(new.run_unit_mo_ids, rec.run_unit_mo_ids)
        self.assertFalse(new.auto_evidence_snapshot)
        self.assertFalse(new.result)
        self.assertEqual(new.quantity_inspected, 0)
        self.assertFalse(new.line_ids.measured_value)
        self.assertNotEqual(new.approval_request_id, rec.approval_request_id)
        self.assertNotEqual(new.approval_state, 'approved')
        new.action_start_inspection()
        new.line_ids.write({'measured_value': 'SYNTHETIC rechecked', 'result': 'pass'})
        new.write({'quantity_inspected': 1, 'quantity_accepted': 1, 'result': 'pass'})
        with self.assertRaises(UserError), self.cr.savepoint():
            new.action_decide()
        new.correction_reason = 'SYNTHETIC new measurement after historical report'
        new.action_decide()
        self.assertEqual(rec.auto_evidence_snapshot, original)
        self.assertFalse(new._run_can_accumulate())

    def test_link_and_frozen_flag_cannot_be_supplied_by_client(self):
        for values in ({'correction_of_id': 1}, {'run_scope_frozen': True}):
            with self.assertRaises(UserError), self.cr.savepoint():
                self.PQC.create(dict(product_id=self.product.id, quantity_inspected=0, **values))
        with self.assertRaises(UserError), self.cr.savepoint():
            self.PQC.with_context(default_run_scope_frozen=True).create({
                'product_id': self.product.id, 'quantity_inspected': 0})

    def test_legacy_snapshot_missing_empty_new_keys_still_matches(self):
        rec = self._draft()
        self._measure(rec)
        rec.action_decide()
        before = deepcopy(rec.auto_evidence_snapshot['source'])
        self.assertNotIn('correction_of_id', before)
        self.assertNotIn('correction_reason', before)
        self.assertTrue(rec._auto_source_matches(before))
        wrong = dict(before, quantity_inspected=9)
        self.assertFalse(rec._auto_source_matches(wrong))

    def test_stock_reader_cannot_edit_or_create_reinspection(self):
        user = new_test_user(self.env(context=dict(self.env.context, no_reset_password=True)),
                            login='synthetic-legacy-reader', groups='base.group_user,stock.group_stock_user')
        rec = self._draft(state='decided').with_user(user)
        with self.assertRaises(AccessError), self.cr.savepoint():
            rec.action_create_reinspection()

    def test_form_has_server_aligned_input_and_scope_locks(self):
        arch = self.PQC.with_user(self.operator).get_view(
            self.env.ref('iatf_process_inspection.view_process_inspection_form').id, 'form')['arch']
        self.assertIn('inspection_input_locked', arch)
        self.assertIn('action_create_reinspection', arch)

    def test_completed_units_split_after_inspection_starts_without_double_count(self):
        MO = self.env['mrp.production']
        if 'is_ip_unit_mo' not in MO._fields:
            self.skipTest('injection_worksite required for actual unit completion')
        product = self.env['product.product'].create({
            'name': 'SYNTHETIC split run', 'is_storable': True, 'tracking': 'lot'})
        bom = self.env['mrp.bom'].create({'product_tmpl_id': product.product_tmpl_id.id,
            'product_id': product.id, 'product_qty': 1, 'type': 'normal', 'company_id': self.company.id})
        plan = MO.create({'product_id': product.id, 'product_qty': 3, 'bom_id': bom.id})
        mold = self.env['injection.mold'].create({'name': 'SYNTHETIC split mold',
            'code': 'SPLIT-%s' % plan.id, 'product_id': product.id, 'cavity_count': 1,
            'company_id': self.company.id})
        units = MO.browse()
        for index in range(3):
            unit = MO.create({'product_id': product.id, 'product_qty': 1, 'bom_id': bom.id,
                              'is_ip_unit_mo': True, 'parent_planning_mo_id': plan.id})
            self._approve_control_plan(unit)
            unit.actual_mold_id = mold
            unit.lot_producing_id = self.env['stock.lot'].create({
                'name': 'SYNTHETIC split-%s' % unit.id, 'product_id': product.id,
                'company_id': self.company.id})
            with freeze_time('2026-10-01 00:00:00'):
                unit.action_complete_unit_mo()
            units |= unit
            if index == 0:
                first = self.PQC.search([('production_id', '=', plan.id)])
                first.action_start_inspection()
        runs = self.PQC.search([('production_id', '=', plan.id)], order='id')
        self.assertEqual(len(runs), 2)
        self.assertEqual(first.quantity_produced, 1)
        self.assertEqual(first.run_unit_mo_ids, units[:1].ids)
        self.assertEqual(runs[-1].quantity_produced, 2)
        self.assertEqual(runs[-1].run_unit_mo_ids, units[1:].ids)
        for unit in units:
            unit._create_pqc_inspection()
        self.assertEqual(self.PQC.search_count([('production_id', '=', plan.id)]), 2)
        self.assertEqual(sum(runs.mapped('quantity_produced')), 3)
