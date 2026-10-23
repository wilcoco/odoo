from odoo import Command,fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestDrawingAgreement(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author=new_test_user(cls.env,login='p1-drawing-author',groups='iatf_drawing_management.group_drawing_user,iatf_document_control.group_document_user')
        cls.manager=new_test_user(cls.env,login='p1-drawing-manager',groups='iatf_drawing_management.group_drawing_manager,iatf_document_control.group_document_manager,iatf_change_management.group_change_management_user')
        cls.product=cls.env['product.product'].create({'name':'SYNTHETIC drawing part'})
        category=cls.env['iatf.document.category'].create({'name':'SYNTHETIC agreement','code':'P1-AGREEMENT'})
        customer=cls.env['res.partner'].create({'name':'SYNTHETIC drawing customer'})
        cls.doc=cls.env['iatf.document'].with_user(cls.author).create({'name':'SYNTHETIC inspection agreement',
            'category_id':category.id,'quality_evidence_kind':'drawing_agreement','quality_product_ids':[Command.set(cls.product.ids)],
            'quality_drawing_number':'SYN-DWG-1','quality_drawing_revision':'A','quality_agreement_number':'SYN-AGR-1',
            'quality_agreement_customer_id':customer.id,'quality_agreement_interval_months':3,
            'quality_agreement_line_ids':[Command.create({'name':'SYN length','criterion':'SYN tolerance','output_document':'SYN report','process_name':'SYN assembly','frequency':'SYN per lot'})],
            'reviewer_id':cls.manager.id,'approver_id':cls.manager.id})
        file=cls.env['ir.attachment'].with_user(cls.author).create({'name':'SYNTHETIC signed agreement.txt','raw':b'Synthetic agreement only','res_model':'iatf.document','res_id':cls.doc.id})
        cls.doc.attachment_ids=[Command.set(file.ids)]
        cls.doc.action_submit_review();cls.doc.with_user(cls.manager).action_approve()
    def _check(self,**values):
        vals={'name':'SYNTHETIC drawing comparison','agreement_document_id':self.doc.id,'product_id':self.product.id,
            'planned_date':fields.Date.today(),'checked_date':fields.Date.today(),
            'actual_drawing_number':'SYN-DWG-1','actual_revision':'A','actual_agreement_number':'SYN-AGR-1',
            'check_method':'SYNTHETIC compare workstation controlled copy','trace_exception':'SYNTHETIC preproduction drawing review',
            'approval_line_ids':[Command.create({'user_id':self.manager.id})]}
        vals.update(values)
        return self.env['iatf.drawing.conformity.check'].with_user(self.author).create(vals)
    def _complete(self,record):
        record.action_submit_approval();record.with_user(self.manager).action_approve_approval();record.action_complete_evidence()
    def test_agreement_lines_and_completed_criteria_preserved(self):
        line=self.doc.quality_agreement_line_ids
        with self.assertRaises(UserError):line.criterion='Forged'
        record=self._check();self._complete(record)
        snapshot=record.completion_snapshot
        self.doc.with_user(self.manager).action_new_revision()
        line.criterion='SYN changed tolerance'
        self.assertEqual(record.completion_snapshot,snapshot)
        self.assertEqual(self.doc.revision_ids.sorted('id')[-1].quality_metadata['agreement_items'][0]['criterion'],'SYN tolerance')
        self.assertEqual(record.result,'match')
    def test_wrong_revision_requires_action_and_stays_mismatch(self):
        record=self._check(actual_revision='OLD')
        with self.assertRaises(UserError):record.action_submit_approval()
        record.action_note='SYNTHETIC recall old controlled copy'
        self._complete(record)
        self.assertEqual(record.result,'mismatch')
        with self.assertRaises(UserError):record.actual_revision='A'
    def test_new_drawing_revision_invalidates_pending_review(self):
        record=self._check();record.action_submit_approval()
        self.doc.with_user(self.manager).action_new_revision()
        with self.assertRaises(UserError):record.with_user(self.manager).action_approve_approval()
