"""Real business approvals, immutable history, company and content boundaries."""
from datetime import timedelta
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestInspectionEvidence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group='cams_inspection_master.group_inspection_user'
        cls.author=new_test_user(cls.env,login='p1-inspection-author',groups=group+',iatf_document_control.group_document_user')
        cls.reviewer=new_test_user(cls.env,login='p1-inspection-reviewer',groups='cams_inspection_master.group_inspection_manager,iatf_document_control.group_document_manager')
        change_group=cls.env.ref('iatf_change_management.group_change_management_user',raise_if_not_found=False)
        if change_group:cls.reviewer.write({'groups_id':[Command.link(change_group.id)]})
        cls.second=new_test_user(cls.env,login='p1-inspection-second',groups=group)
        cls.outsider=new_test_user(cls.env,login='p1-inspection-outsider',groups='base.group_user')
        cls.today=fields.Date.today()
        cls.product=cls.env['product.product'].create({'name':'SYNTHETIC P1 part','is_storable':True})
        cls.lot=cls.env['stock.lot'].create({'name':'SYNTHETIC-P1-LOT','product_id':cls.product.id,'company_id':cls.env.company.id})
        cls.workcenter=cls.env['mrp.workcenter'].create({'name':'SYNTHETIC P1 workcenter','company_id':cls.env.company.id})
        cls.category=cls.env['iatf.document.category'].create({'name':'SYNTHETIC P1 criteria','code':'P1-SYNTHETIC'})
        cls.customer=cls.env['res.partner'].create({'name':'SYNTHETIC customer'})

    def _master(self, kind='limit_sample'):
        values={'name':'SYNTHETIC controlled '+kind,'category_id':self.category.id,
            'owner_id':self.author.id,'reviewer_id':self.second.id,'approver_id':self.reviewer.id,
            'quality_evidence_kind':kind,'quality_product_ids':[Command.set(self.product.ids)],
            'quality_valid_from':self.today-timedelta(days=1),'quality_valid_until':self.today+timedelta(days=30),
            'physical_reference':'SYNTHETIC SAMPLE','storage_location':'Test laboratory',
            'quality_sample_type':'boundary','quality_characteristic':'SYNTHETIC visible mark',
            'quality_customer_id':self.customer.id,'quality_cycle_note':'SYNTHETIC planned test only',
            'quality_plan_year':self.today.year,'quality_plan_months':str(self.today.month),'quality_test_kind':'SYNTHETIC test'}
        doc=self.env['iatf.document'].with_user(self.author).create(values)
        doc.action_submit_review()
        doc.with_user(self.reviewer).action_approve()
        return doc

    def _record(self, periodic=False, **values):
        master=self._master('reliability_plan' if periodic else 'limit_sample')
        vals={'name':'SYNTHETIC evidence','product_id':self.product.id,'lot_id':self.lot.id,
            'workcenter_id':self.workcenter.id,'responsible_id':self.author.id,
            'approval_line_ids':[Command.create({'sequence':10,'user_id':self.reviewer.id}),
                                 Command.create({'sequence':20,'user_id':self.second.id})]}
        if periodic:
            attachment=self.env['ir.attachment'].with_user(self.author).create({'name':'SYNTHETIC result.txt','raw':b'actual test fixture'})
            vals.update(plan_document_id=master.id,planned_date=self.today,actual_date=self.today,
                sample_count=2,result='pass',result_note='SYNTHETIC measured outcome',attachment_ids=[Command.set(attachment.ids)])
        else:vals.update(sample_document_id=master.id,result='ok',check_detail='SYNTHETIC appearance and expiry checked')
        vals.update(values)
        return self.env['cams.periodic.test' if periodic else 'cams.limit.sample.check'].with_user(self.author).create(vals)

    def _complete(self, record):
        record.action_submit_approval()
        record.with_user(self.reviewer).action_approve_approval()
        record.with_user(self.second).action_approve_approval()
        record.action_complete_evidence()

    def test_complete_revision_preserves_snapshot_and_previous_approval(self):
        record=self._record()
        self._complete(record)
        snapshot=record.completion_snapshot
        request=record.approval_request_id
        self.assertEqual(record.evidence_state,'done')
        self.assertEqual(snapshot['quality_criteria'][str(record.sample_document_id.id)]['quality_characteristic'],'SYNTHETIC visible mark')
        record.action_complete_evidence()  # idempotent completion
        action=record.action_new_evidence_revision()
        new=self.env[record._name].with_user(self.author).browse(action['res_id'])
        self.assertEqual(new.evidence_revision,2)
        self.assertEqual(new.previous_evidence_id,record.id)
        self.assertEqual(new.approval_state,'draft')
        self.assertFalse(new.completion_snapshot)
        new.write({'check_detail':'SYNTHETIC next observation'})
        self.assertEqual(record.completion_snapshot,snapshot)
        self.assertEqual(request.state,'approved')
        with self.assertRaises(UserError):record.action_new_evidence_revision()
        with self.assertRaises(UserError):record.write({'result':'ng'})
        with self.assertRaises(UserError):record.with_user(self.reviewer).unlink()
        with self.assertRaises(UserError):record.action_reset_approval()

    def test_rejection_changes_require_new_approval(self):
        record=self._record()
        record.action_submit_approval()
        request=record.approval_request_id
        record.with_user(self.reviewer).approval_request_id.action_reject(reason='SYNTHETIC clarify check')
        record.write({'check_detail':'SYNTHETIC corrected observation'})
        self._complete(record)
        self.assertEqual(request.state,'rejected')
        self.assertNotEqual(record.approval_request_id,request)

    def test_completion_and_context_forgery_blocked(self):
        record=self._record()
        with self.assertRaises(UserError):record.action_complete_evidence()
        for vals in ({'evidence_state':'done'},{'completion_snapshot':{}},{'evidence_revision':9}):
            with self.assertRaises(UserError):record.with_context(_cams_evidence_transition=True).write(vals)
        with self.assertRaises(UserError):
            self.env[record._name].with_user(self.author).with_context(default_evidence_state='done').create({'name':'SYNTHETIC forged'})

    def test_two_distinct_reviewers_and_sequence(self):
        record=self._record(approval_line_ids=[Command.create({'user_id':self.reviewer.id})])
        with self.assertRaises(UserError):record.action_submit_approval()
        record=self._record()
        record.action_submit_approval()
        with self.assertRaises(UserError):record.with_user(self.second).action_approve_approval()
        with self.assertRaises(UserError):record.write({'check_detail':'Changed during review'})

    def test_master_revision_invalidates_pending_approval_not_completed_snapshot(self):
        completed=self._record()
        self._complete(completed)
        snapshot=completed.completion_snapshot
        completed.sample_document_id.with_user(self.reviewer).action_new_revision()
        completed.sample_document_id.write({'quality_characteristic':'SYNTHETIC changed criterion'})
        self.assertEqual(completed.completion_snapshot,snapshot)
        pending=self._record()
        pending.action_submit_approval()
        pending.sample_document_id.with_user(self.reviewer).action_new_revision()
        with self.assertRaises(UserError):pending.with_user(self.reviewer).action_approve_approval()

    def test_expired_sample_cannot_be_called_valid(self):
        record=self._record()
        doc=record.sample_document_id.with_user(self.reviewer)
        doc.action_new_revision()
        doc.write({'quality_valid_from':self.today-timedelta(days=30),'quality_valid_until':self.today-timedelta(days=1)})
        doc.action_submit_review();doc.action_approve()
        with self.assertRaises(UserError):record.action_submit_approval()
        record.write({'result':'ng','action_note':'SYNTHETIC replace expired sample'})
        self._complete(record)

    def test_periodic_requires_actual_result_file_lot_and_plan_month(self):
        record=self._record(periodic=True,actual_date=False)
        with self.assertRaises(UserError):record.action_submit_approval()
        record.write({'actual_date':self.today,'lot_id':False,'trace_exception':'Test cannot omit LOT'})
        with self.assertRaises(UserError):record.action_submit_approval()
        record.write({'lot_id':self.lot.id,'planned_date':self.today.replace(year=self.today.year+1)})
        with self.assertRaises(UserError):record.action_submit_approval()
        record.write({'planned_date':self.today})
        self._complete(record)
        self.assertEqual(record.completion_snapshot['values']['result'],'pass')
        calendar=str(record.plan_document_id.quality_test_calendar)
        self.assertEqual(calendar.count('<tr>'),13)
        self.assertIn('<th>%s월</th><td>계획</td><td>0</td><td>1</td><td>0</td>' % self.today.month,calendar)

    def test_attachment_bytes_cannot_change_after_submission_or_completion(self):
        record=self._record(periodic=True)
        attachment=record.attachment_ids
        record.action_submit_approval()
        with self.assertRaises(UserError):attachment.write({'raw':b'replaced'})
        record.with_user(self.reviewer).action_approve_approval()
        record.with_user(self.second).action_approve_approval()
        record.action_complete_evidence()
        with self.assertRaises(UserError):attachment.unlink()

    def test_company_scope_and_outsider_no_access(self):
        record=self._record()
        with self.assertRaises(AccessError):record.with_user(self.outsider).read(['name'])
        other=self.env['res.company'].create({'name':'SYNTHETIC other evidence company'})
        with self.assertRaises(AccessError):
            record.with_user(self.author).with_context(allowed_company_ids=[other.id]).read(['name'])
        other_product=self.env['product.product'].create({'name':'SYNTHETIC unrelated product'})
        with self.assertRaises(ValidationError),self.cr.savepoint():record.write({'product_id':other_product.id})

    def test_unapproved_or_wrong_product_master_rejected(self):
        record=self._record()
        record.sample_document_id.with_user(self.reviewer).action_new_revision()
        with self.assertRaises(UserError):record.action_submit_approval()

    def test_trace_exception_cannot_silently_replace_lot_and_equipment(self):
        record=self._record(lot_id=False,workcenter_id=False)
        with self.assertRaises(UserError):record.action_submit_approval()
        record.write({'trace_exception':'SYNTHETIC customer boundary sample before series production'})
        self._complete(record)
