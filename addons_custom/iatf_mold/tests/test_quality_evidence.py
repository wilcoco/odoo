from odoo import Command,fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestMoldEvidence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author=new_test_user(cls.env,login='p1-mold-author',groups='iatf_mold.group_mold_user')
        cls.reviewer=new_test_user(cls.env,login='p1-mold-reviewer',groups='iatf_mold.group_mold_manager')
        cls.product=cls.env['product.product'].create({'name':'SYNTHETIC mold evidence product','is_storable':True,'tracking':'lot'})
        cls.lot=cls.env['stock.lot'].create({'name':'SYNTHETIC mold trial LOT','product_id':cls.product.id,'company_id':cls.env.company.id})
        cls.wc=cls.env['mrp.workcenter'].create({'name':'SYNTHETIC trial machine','company_id':cls.env.company.id})
        cls.mold=cls.env['injection.mold'].create({'name':'SYNTHETIC mold evidence','product_id':cls.product.id,'current_shots':500,'cavity_count':2,'clean_cycle_days':30})
    def _photo(self,label):
        return self.env['ir.attachment'].with_user(self.author).create({'name':'SYNTHETIC '+label+'.txt','raw':label.encode(),'company_id':self.env.company.id})
    def _values(self):
        return {'mold_id':self.mold.id,'product_id':self.product.id,'lot_id':self.lot.id,'workcenter_id':self.wc.id,
            'approval_line_ids':[Command.create({'user_id':self.reviewer.id})]}
    def _complete(self,record):
        record.action_submit_approval()
        self.assertEqual(record.approval_request_id.snapshot,record.with_user(self.reviewer)._approval_snapshot())
        record.with_user(self.reviewer).action_approve_approval();record.action_complete_evidence()
    def test_development_counter_revision_does_not_double_plc_shots(self):
        record=self.env['iatf.mold.tryout'].with_user(self.author).create(dict(self._values(),shot_count=10,ok_qty=18,ng_qty=2,
            counter_start=100,counter_end=110,counter_confirmed=True,counter_includes_tryout=True,conclusion='pass',
            attachment_ids=[Command.link(self._photo('counter proof').id)]))
        self._complete(record)
        self.assertEqual((self.mold.dev_shots,self.mold.dev_shots_in_counter,self.mold.current_shots),(10,10,500))
        record.action_done()
        new=self.env[record._name].with_user(self.author).browse(record.action_new_evidence_revision()['res_id'])
        new.write({'counter_end':111,'shot_count':11})
        self._complete(new)
        self.assertEqual((self.mold.dev_shots,self.mold.current_shots),(11,500))
        self.assertEqual(record.completion_snapshot['values']['shot_count'],10)
        with self.assertRaises(UserError):record.shot_count=100
    def test_cleaning_requires_before_after_and_preserves_photos(self):
        before=self._photo('before');after=self._photo('after')
        record=self.env['iatf.mold.maintenance'].with_user(self.author).create(dict(self._values(),maintenance_type='clean',
            work_description='SYNTHETIC actual cleaning',duration_hours=1,result='ok',cleaning_method='SYNTHETIC procedure',
            cleaning_agent='SYNTHETIC confirmed solvent',cleaning_before_photo_ids=[Command.link(before.id)]))
        with self.assertRaises(UserError):record.action_submit_approval()
        record.cleaning_after_photo_ids=[Command.link(after.id)]
        self._complete(record)
        self.assertEqual(self.mold.last_clean_date,fields.Date.today())
        self.assertEqual(record.attachment_ids,before|after)
        with self.assertRaises(UserError):before.write({'raw':b'changed'})
        with self.assertRaises(UserError):record.action_draft()

    def test_temperature_ng_closure_preserves_original_measurement(self):
        self.mold.write({'preheat_temp_min': 60, 'preheat_temp_max': 80})
        record=self.env['iatf.mold.temp.log'].with_user(self.author).create(dict(self._values(),
            temperature=90, point='fixed', method='ir', log_type='preheat'))
        with self.assertRaises(UserError):record.action_submit_approval()
        record.action_note='SYNTHETIC reheated and scheduled separate remeasurement'
        self._complete(record)
        snapshot=record.completion_snapshot
        self.assertEqual(record.spec_result,'ng')
        with self.assertRaises(UserError):record.write({'notes':'changed completed record'})
        action=record.action_new_evidence_revision()
        self.assertEqual(action['res_model'],'iatf.mold.temp.remeasure')
        wizard=self.env[action['res_model']].with_user(self.author).create({'source_id':record.id,
            'temperature':70,'method':'ir','point':'fixed','reason':'SYNTHETIC remeasured','confirmed':True})
        new=self.env[record._name].with_user(self.author).browse(wizard.action_remeasure()['res_id'])
        self.assertEqual(new.evidence_revision,2)
        self.assertEqual(new.temperature,70)
        self._complete(new)
        self.assertEqual(new.spec_result,'ok')
        self.assertEqual(record.completion_snapshot,snapshot)
        self.assertEqual(record.spec_result,'ng')
        self.assertEqual(snapshot['values']['temperature'],90)
