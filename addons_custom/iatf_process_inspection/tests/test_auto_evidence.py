"""Normal quality roles, finite evidence, company isolation and real RR races."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import TestCase
from uuid import uuid4
from unittest.mock import patch

from psycopg2.errors import SerializationFailure

from odoo import api, Command, sql_db, SUPERUSER_ID
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestProcessAutoEvidence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        assert 'iatf.spc.study' in cls.env and 'iatf.risk.register' in cls.env, (
            'Install iatf_spc and iatf_risk for this integration boundary test')
        cls.company = cls.env.company
        cls.other = cls.env['res.company'].create({'name': 'SYNTHETIC auto evidence other company'})
        cls.product = cls.env['product.product'].create({
            'name': 'SYNTHETIC automatic quality evidence', 'is_storable': True, 'tracking': 'lot'})
        cls.stock = cls.env['stock.warehouse'].search([
            ('company_id', '=', cls.company.id)], limit=1).lot_stock_id
        user_env = cls.env(context=dict(cls.env.context, no_reset_password=True,
                                       mail_create_nosubscribe=True, mail_notrack=True))
        cls.quality_user = new_test_user(user_env, login='synthetic-auto-evidence-quality',
            groups='base.group_user,stock.group_stock_user,mrp.group_mrp_user,'
                   'iatf_process_inspection.group_process_inspection_user,'
                   'iatf_incoming_inspection.group_incoming_inspection_user,'
                   'iatf_shipping_inspection.group_shipping_inspection_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.stock_user = new_test_user(user_env, login='synthetic-auto-evidence-stock',
            groups='base.group_user,stock.group_stock_user', company_id=cls.company.id,
            company_ids=[Command.set(cls.company.ids)])

    def _study(self, **values):
        return self.env['iatf.spc.study'].create(dict({
            'title': 'SYNTHETIC auto collection', 'company_id': self.company.id,
            'product_id': self.product.id, 'characteristic_name': 'Thickness',
            'subgroup_size': 5, 'state': 'collecting'}, **values))

    def _inspection(self, measured='12.0', **values):
        result = values.get('result', 'pass')
        return self.env['iatf.process.inspection'].create(dict({
            'product_id': self.product.id, 'company_id': self.company.id,
            'inspection_stage': 'final', 'quantity_produced': 1,
            'quantity_inspected': 1, 'quantity_accepted': int(result == 'pass'),
            'quantity_rejected': int(result == 'fail'), 'result': result,
            'line_ids': [Command.create({'characteristic_name': 'Thickness',
                'measured_value': measured, 'result': result if result in ('pass', 'fail') else 'pass'})],
        }, **values)).with_user(self.quality_user)

    def test_quality_without_spc_role_collects_only_matching_study_once(self):
        study = self._study()
        foreign = self._study(company_id=self.other.id)
        different = self._study(characteristic_name='Unrelated characteristic')
        self.assertFalse(self.env['iatf.spc.study'].with_user(self.quality_user).has_access('read'))
        self.assertFalse(self.env['iatf.nonconformity'].with_user(self.quality_user).has_access('create'))
        # Historical unmarked values must not be promoted by a new measurement.
        legacy = self.env['iatf.spc.subgroup'].create({
            'study_id': study.id, 'x1': 99, 'sample_count': 1, 'sequence': 1})
        legacy.flush_recordset()
        self.env.cr.execute('UPDATE iatf_spc_subgroup SET filled_mask=NULL WHERE id=%s', [legacy.id])
        legacy.invalidate_recordset()
        pqc = self._inspection('0')
        pqc.action_decide()
        pqc.action_decide()
        study.invalidate_recordset()
        fresh = study.subgroup_ids - legacy
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh._get_values(), [0.0])
        self.assertEqual(fresh.origins, 'pqc:%s:%s' % (pqc.id, pqc.line_ids.id))
        self.assertFalse(legacy.filled_mask)
        self.assertFalse(foreign.subgroup_ids | different.subgroup_ids)
        self.assertEqual(pqc.state, 'decided')
        self.assertTrue(pqc.auto_evidence_snapshot)
        self.assertEqual(pqc.auto_evidence_snapshot['recorded_by_id'], self.quality_user.id)
        # The existing private helper unit contract also checks real caller/source.
        draft = self._inspection('12', result=False)
        draft._auto_feed_spc()
        self.assertEqual(draft.state, 'draft')
        self.assertEqual(fresh._get_values(), [0.0, 12.0])

    def test_source_permissions_company_and_frozen_evidence(self):
        self._study()
        pqc = self._inspection()
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            pqc.with_user(self.stock_user).action_decide()
        bad = self._inspection(company_id=self.other.id)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            bad.action_decide()
        foreign_lot = self.env['stock.lot'].create({
            'name': 'SYNTHETIC other company lot', 'product_id': self.product.id,
            'company_id': self.other.id})
        wrong = self._inspection(lot_id=foreign_lot.id)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            wrong.action_decide()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env['iatf.process.inspection'].with_context(
                default_auto_evidence_snapshot={'version': 1}).create({
                    'product_id': self.product.id, 'quantity_inspected': 1})
        pqc.action_decide()
        for mutate in (
                lambda: pqc.write({'auto_evidence_snapshot': False}),
                lambda: pqc.write({'product_id': self.product.id}),
                lambda: pqc.line_ids.write({'measured_value': '100'}),
                lambda: self.env['iatf.process.inspection.line'].with_user(self.quality_user)
                    .with_context(default_inspection_id=pqc.id).create({
                        'characteristic_name': 'Added later', 'measured_value': '1'})):
            with self.assertRaises(UserError), self.env.cr.savepoint():
                mutate()
        self.assertEqual(pqc.line_ids.measured_value, '12.0')

    def test_nonfinite_measurements_fail_atomically_but_observation_is_valid(self):
        study = self._study()
        for value in ('nan', 'inf', '-Infinity', '1e999'):
            pqc = self._inspection(value)
            with self.assertRaises(UserError), self.env.cr.savepoint():
                pqc.action_decide()
            self.assertEqual(pqc.state, 'draft')
            self.assertFalse(pqc.auto_evidence_snapshot)
        observation = self._inspection('Visual observation: no damage')
        observation.action_decide()
        self.assertEqual(observation.state, 'decided')
        self.assertFalse(study.subgroup_ids)

    def test_failure_creates_scoped_nc_and_hold_without_moving_or_unreserving_stock(self):
        self._study()
        lot = self.env['stock.lot'].create({
            'name': 'SYNTHETIC preserve stock on failed inspection', 'product_id': self.product.id,
            'company_id': self.company.id})
        self.env['stock.quant']._update_available_quantity(self.product, self.stock, 10, lot_id=lot)
        shelf = self.env['stock.location'].create({
            'name': 'SYNTHETIC reserved shelf', 'usage': 'internal', 'company_id': self.company.id})
        reservation = self.env['stock.move'].create({
            'name': 'SYNTHETIC preserve other reservation', 'product_id': self.product.id,
            'product_uom_qty': 3, 'product_uom': self.product.uom_id.id,
            'location_id': self.stock.id, 'location_dest_id': shelf.id,
            'company_id': self.company.id})
        reservation._action_confirm()
        reservation._action_assign()
        quants = self.env['stock.quant'].search([('lot_id', '=', lot.id)])
        before = [(q.id, q.quantity, q.reserved_quantity, q.location_id.id) for q in quants]
        self.assertEqual(sum(q.reserved_quantity for q in quants), 3)
        lot.write({'quality_hold': True, 'hold_reason': 'Existing independent hold'})
        moves_before = self.env['stock.move'].search_count([])
        risks = self.env['iatf.risk.register']
        own = risks.create({'title': 'SYNTHETIC matching risk',
            'description': self.product.name, 'company_id': self.company.id,
            'responsible_id': self.quality_user.id})
        foreign = risks.create({'title': 'SYNTHETIC foreign risk',
            'description': self.product.name, 'company_id': self.other.id})
        pqc = self._inspection('70', result='fail', lot_id=lot.id)
        pqc.action_decide()
        nc = pqc.nonconformity_id.sudo()
        self.assertTrue(nc)
        self.assertEqual(nc.company_id, self.company)
        self.assertEqual(nc.product_id, self.product)
        self.assertEqual(nc.lot_id, lot)
        self.assertEqual(nc.detected_by, self.quality_user)
        pqc.action_decide()
        quants.invalidate_recordset()
        lot.invalidate_recordset()
        self.assertEqual([(q.id, q.quantity, q.reserved_quantity, q.location_id.id) for q in quants], before)
        self.assertEqual(self.env['stock.move'].search_count([]), moves_before)
        self.assertTrue(lot.quality_hold)
        self.assertIn('Existing independent hold', lot.hold_reason)
        self.assertEqual(lot.hold_reason.count('[PQC:'), 1)
        self.assertEqual(len(own.activity_ids), 1)
        self.assertFalse(foreign.activity_ids)
        self.assertEqual(self.env['iatf.nonconformity'].search_count([
            ('product_id', '=', self.product.id), ('lot_id', '=', lot.id)]), 1)

    def _run_concurrent_same_and_different_inspections(self):
        """Committed synthetic fixtures use independent cursors in this test DB only."""
        database, company_id = sql_db.db_connect(self.env.cr.dbname), self.company.id
        results = []
        for same in (True, False):
            label = 'SYNTHETIC auto-evidence race ' + uuid4().hex
            with database.cursor() as cr:
                fixture = api.Environment(cr, SUPERUSER_ID, {
                    'allowed_company_ids': [company_id], 'no_reset_password': True,
                    'mail_create_nosubscribe': True, 'mail_notrack': True})
                # A fixture user must not subscribe to the production digest.
                # It would also lock the main TransactionCase's digest row.
                with patch.object(type(fixture['digest.digest']), 'write', return_value=True):
                    user = new_test_user(fixture, login=label,
                        groups='base.group_user,stock.group_stock_user,iatf_process_inspection.group_process_inspection_user',
                        company_id=company_id, company_ids=[Command.set([company_id])])
                product = fixture['product.product'].create({'name': label})
                study = fixture['iatf.spc.study'].create({'title': label,
                    'product_id': product.id, 'company_id': company_id,
                    'characteristic_name': 'Thickness', 'subgroup_size': 5, 'state': 'collecting'})
                records = fixture['iatf.process.inspection']
                for value in (1, 2):
                    records |= fixture['iatf.process.inspection'].create({
                        'product_id': product.id, 'company_id': company_id,
                        'quantity_inspected': 1, 'result': 'pass',
                        'line_ids': [Command.create({'characteristic_name': 'Thickness',
                            'measured_value': str(value), 'result': 'pass'})]})
                uid, study_id = user.id, study.id
                ids = [records[0].id, records[0 if same else 1].id]
                cr.commit()
            ready, pinned = Event(), Event()

            def worker(index):
                for attempt in range(4):
                    try:
                        with database.cursor() as cr:
                            other = api.Environment(cr, uid, {'allowed_company_ids': [company_id],
                                'mail_create_nosubscribe': True, 'mail_notrack': True})
                            if index == 1 and attempt == 0:
                                self.assertTrue(ready.wait(15))
                                cr.execute('SELECT id FROM iatf_spc_study WHERE id=%s', [study_id])
                                pinned.set()
                            other['iatf.process.inspection'].browse(ids[index]).action_decide()
                            if index == 0:
                                ready.set()
                                self.assertTrue(pinned.wait(15))
                            cr.commit()
                            return attempt
                    except SerializationFailure:
                        if attempt == 3:
                            raise
                raise AssertionError('retry exhausted')

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker, index) for index in (0, 1)]
                retries = [future.result(timeout=45) for future in futures]
            self.assertGreaterEqual(sum(retries), 1, 'The stale transaction must retry, not be swallowed')
            with database.cursor() as cr:
                inspect = api.Environment(cr, SUPERUSER_ID, {'allowed_company_ids': [company_id]})
                groups = inspect['iatf.spc.study'].browse(study_id).subgroup_ids
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups._get_values(), [1.0] if same else [1.0, 2.0])
                origins = groups.origins.split(',')
                self.assertEqual(len(origins), 1 if same else 2)
                self.assertEqual(len(set(origins)), len(origins))
                results.append({'same_inspection': same, 'retries': retries,
                    'values': groups._get_values(), 'origins': origins, 'study_id': study_id})
        return results


def run_auto_evidence_concurrency(env):
    """Run outside TransactionCase's registry/test lock, using this DB only."""
    probe = TestCase()
    probe.env = env
    probe.company = env.company
    return TestProcessAutoEvidence._run_concurrent_same_and_different_inspections(probe)
