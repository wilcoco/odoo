from datetime import timedelta
from odoo import Command,fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestContainerEvidence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author=new_test_user(cls.env,login='p1-container-author',groups='cams_material_control.group_material_user,iatf_packaging.group_packaging_user')
        cls.manager=new_test_user(cls.env,login='p1-container-manager',groups='cams_material_control.group_material_manager,iatf_packaging.group_packaging_manager')
        cls.product=cls.env['product.product'].create({'name':'SYNTHETIC container part','is_storable':True})
        cls.lot=cls.env['stock.lot'].create({'name':'SYNTHETIC container LOT','product_id':cls.product.id,'company_id':cls.env.company.id})
    def _spec(self,**values):
        vals={'product_id':self.product.id,'flow_direction':'internal','outer_packaging_type':'SYNTHETIC tray','outer_quantity':20,
            'trace_exception':'SYNTHETIC specification applies across LOTs',
            'approval_line_ids':[Command.create({'user_id':self.manager.id})]}
        vals.update(values)
        return self.env['iatf.packaging.spec'].with_user(self.author).create(vals)
    def _complete(self,record):
        record.action_submit_approval();record.with_user(self.manager).action_approve_approval();record.action_complete_evidence()
    def _check(self,spec,**values):
        photo=self.env['ir.attachment'].with_user(self.author).create({'name':'SYNTHETIC photo proof.txt','raw':b'Synthetic image substitute in test only'})
        vals={'name':'SYNTHETIC quarterly check','spec_id':spec.id,'product_id':self.product.id,'lot_id':self.lot.id,
            'trace_exception':'SYNTHETIC warehouse check, no production workcenter','cleanliness':'ok','damage':'ok',
            'identification':'ok','mixed_parts':'ok','actual_container_type':'SYNTHETIC tray','actual_quantity':20,
            'attachment_ids':[Command.set(photo.ids)],'approval_line_ids':[Command.create({'user_id':self.manager.id})]}
        vals.update(values)
        return self.env['cams.container.clean'].with_user(self.author).create(vals)
    def test_standard_approval_revision_and_one_active_family(self):
        spec=self._spec()
        with self.assertRaises(UserError):spec.action_activate()
        self._complete(spec)
        self.assertEqual(spec.state,'active')
        snapshot=spec.completion_snapshot
        with self.assertRaises(UserError):spec.outer_quantity=25
        new=self.env[spec._name].with_user(self.author).browse(spec.action_new_evidence_revision()['res_id'])
        new.outer_quantity=25;self._complete(new)
        self.assertEqual(new.state,'active');self.assertEqual(spec.state,'obsolete')
        self.assertEqual(spec.completion_snapshot,snapshot)
    def test_t1_lead_time_needs_recorded_deviation(self):
        today=fields.Date.today()
        spec=self._spec(automated=True,t1_date=today+timedelta(days=20),automation_ready_date=today)
        with self.assertRaises(UserError):spec.action_submit_approval()
        spec.readiness_deviation='SYNTHETIC 10-day shortfall and mitigation agreed'
        self._complete(spec)
        self.assertIn('10-day',spec.completion_snapshot['values']['readiness_deviation'])
    def test_actual_container_mismatch_never_becomes_pass(self):
        spec=self._spec();self._complete(spec)
        record=self._check(spec,actual_quantity=19)
        self.assertEqual(record.result,'ng')
        with self.assertRaises(UserError):record.action_submit_approval()
        record.action_note='SYNTHETIC replace incorrect tray'
        self._complete(record)
        self.assertEqual(record.result,'ng')
        self.assertEqual(record.completion_snapshot['specification']['values']['outer_quantity'],20)
        with self.assertRaises(UserError):record.write({'actual_quantity':20})
    def test_spec_change_invalidates_pending_check_and_preserves_completed(self):
        spec=self._spec();self._complete(spec)
        completed=self._check(spec);self._complete(completed)
        snapshot=completed.completion_snapshot
        pending=self._check(spec);pending.action_submit_approval()
        spec.with_user(self.manager).action_obsolete()
        with self.assertRaises(UserError):pending.with_user(self.manager).action_approve_approval()
        self.assertEqual(completed.completion_snapshot,snapshot)
        self.assertEqual(completed.result,'ok')
