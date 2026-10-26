from copy import deepcopy
from odoo import Command
from odoo.exceptions import AccessError,UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestSourceEvidence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.worker=new_test_user(cls.env,login='p1-source-worker',groups='iatf_work_environment.group_work_environment_user,iatf_document_control.group_document_user')
        cls.manager=new_test_user(cls.env,login='p1-source-manager',groups='iatf_work_environment.group_work_environment_manager,iatf_document_control.group_document_manager')
        cls.category=cls.env['iatf.document.category'].create({'name':'SYNTHETIC layouts','code':'P1-LAYOUT'})
    def _layout(self):
        doc=self.env['iatf.document'].with_user(self.worker).create({'name':'SYNTHETIC layout P01',
            'category_id':self.category.id,'quality_evidence_kind':'work_area_layout','owner_id':self.worker.id,
            'reviewer_id':self.manager.id,'approver_id':self.manager.id})
        photo=self.env['ir.attachment'].with_user(self.worker).create({'name':'SYNTHETIC layout proof.txt',
            'raw':b'SYNTHETIC P01 drawing','res_model':doc._name,'res_id':doc.id,'company_id':self.env.company.id})
        doc.attachment_ids=[Command.link(photo.id)]
        doc.action_submit_review();doc.with_user(self.manager).action_approve()
        return doc,photo
    def _sheet(self,layout=None,purpose='lighting'):
        return self.env['iatf.check.sheet'].with_user(self.manager).create({'name':'SYNTHETIC '+purpose,
            'quality_purpose':purpose,'cycle':'monthly','layout_document_id':layout.id if layout else False,
            'item_ids':[Command.create({'name':'P01 SYNTHETIC measurement location','entry_type':'numeric',
                'check_method':'measure','spec_mode':'min','spec_min':400,'uom_name':'Lux'})]})
    def test_monthly_layout_and_source_snapshot_are_preserved(self):
        layout,photo=self._layout();sheet=self._sheet(layout)
        record=self.env['iatf.check.record'].with_user(self.worker).create({'sheet_id':sheet.id})
        record.line_ids.value=500
        with self.assertRaises(UserError),self.cr.savepoint():record.action_done()
        record.trace_exception='SYNTHETIC room lighting inspection, no production lot or machine'
        record.action_done()
        first=record.snapshot_ids.sorted('id')[0]
        old=deepcopy(first.source_context)
        self.assertEqual(old['purpose'],'lighting')
        self.assertIn(photo,first.source_attachment_ids)
        with self.assertRaises(UserError):photo.write({'raw':b'changed'})
        record.action_draft();record.line_ids.value=600;record.action_done()
        self.assertEqual(len(record.snapshot_ids),2)
        self.assertEqual(first.source_context,old)
    def test_missing_layout_or_numbers_cannot_be_completed(self):
        sheet=self._sheet()
        record=self.env['iatf.check.record'].with_user(self.worker).create({'sheet_id':sheet.id,
            'trace_exception':'SYNTHETIC room inspection'})
        record.line_ids.value=500
        with self.assertRaises(UserError),self.cr.savepoint():record.action_done()
        with self.assertRaises(AccessError):sheet.with_user(self.worker).quality_purpose='general'
        with self.assertRaises(UserError):record.quality_purpose='general'
    def test_foolproof_ng_requires_action_and_trace(self):
        sheet=self._sheet(purpose='foolproof')
        record=self.env['iatf.check.record'].with_user(self.worker).create({'sheet_id':sheet.id,
            'trace_exception':'SYNTHETIC preproduction fixture test'})
        record.line_ids.value=100
        with self.assertRaises(UserError),self.cr.savepoint():record.action_done()
        record.corrective_action='SYNTHETIC fixture placed on hold; actual replacement pending'
        record.action_done()
        self.assertEqual(record.overall_result,'issue')
        self.assertEqual(record.snapshot_ids.source_context['purpose'],'foolproof')
