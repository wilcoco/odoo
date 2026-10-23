from odoo import Command,fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestQualityActivity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author=new_test_user(cls.env,login='p1-spirit-author',groups='cams_quality_activity.group_activity_user,iatf_document_control.group_document_user,iatf_training.group_training_user')
        cls.manager=new_test_user(cls.env,login='p1-spirit-manager',groups='cams_quality_activity.group_activity_manager,iatf_document_control.group_document_manager,iatf_training.group_training_manager')
        cls.executive=new_test_user(cls.env,login='p1-spirit-executive',groups='cams_quality_activity.group_activity_manager,cams_ops_policy.group_approver_executive,iatf_document_control.group_document_manager')
        cls.department=cls.env['hr.department'].create({'name':'SYNTHETIC quality department','company_id':cls.env.company.id})
        cls.employee=cls.env['hr.employee'].create({'name':'SYNTHETIC quality attendee','company_id':cls.env.company.id,'department_id':cls.department.id})
        cls.category=cls.env['iatf.document.category'].create({'name':'SYNTHETIC annual activity','code':'P1-SPIRIT'})
        cls.today=fields.Date.today()
    def _plan(self,approver=None):
        approver=approver or self.executive
        doc=self.env['iatf.document'].with_user(self.author).create({'name':'SYNTHETIC annual quality activity',
            'category_id':self.category.id,'quality_evidence_kind':'quality_activity_plan','owner_id':self.author.id,
            'reviewer_id':self.manager.id,'approver_id':approver.id,'quality_activity_year':self.today.year,
            'quality_training_planned_date':self.today,'quality_check_planned_date':self.today,
            'quality_target_department_ids':[Command.set(self.department.ids)]})
        doc.action_submit_review()
        return doc
    def _activity(self,plan,kind='inspection',**values):
        vals={'name':'SYNTHETIC quality '+kind,'plan_document_id':plan.id,'activity_type':kind,'department_id':self.department.id,
            'trace_exception':'SYNTHETIC department quality meeting, no production LOT or machine',
            'result_note':'SYNTHETIC actual activity record','improvement_type':'none',
            'approval_line_ids':[Command.create({'user_id':self.manager.id})]}
        vals.update(values)
        return self.env['cams.quality.activity'].with_user(self.author).create(vals)
    def _complete(self,record,approver=None):
        record.action_submit_approval();record.with_user(approver or self.manager).action_approve_approval();record.action_complete_evidence()
    def test_plan_needs_independent_executive_approval(self):
        wrong=self._plan(self.manager)
        with self.assertRaises(UserError):wrong.with_user(self.manager).action_approve()
        plan=self._plan();plan.with_user(self.executive).action_approve()
        activity=self._activity(plan);self._complete(activity)
        self.assertEqual(plan.quality_activity_check_count,1)
        with self.assertRaises(UserError):activity.result_note='Changed after approval'
    def test_training_reuses_real_approved_training_record(self):
        plan=self._plan();plan.with_user(self.executive).action_approve()
        training=self.env['iatf.training.record'].with_user(self.author).create({'title':'SYNTHETIC quality education',
            'employee_ids':[Command.set(self.employee.ids)],'training_date':self.today,
            'approval_line_ids':[Command.create({'user_id':self.manager.id})]})
        activity=self._activity(plan,'training',training_ids=[Command.set(training.ids)])
        with self.assertRaises(UserError):activity.action_submit_approval()
        # Existing training approves the completed report. Completing it after
        # approval changes the report and correctly invalidates that approval.
        training.action_complete();training.action_submit_approval();training.with_user(self.manager).action_approve_approval()
        self._complete(activity)
        self.assertEqual(activity.completion_snapshot['training_evidence'][0]['participant_count'],1)
        self.assertEqual(plan.quality_activity_training_count,1)
    def test_department_award_requires_executive_final_step(self):
        plan=self._plan();plan.with_user(self.executive).action_approve()
        award=self._activity(plan,'award',award_month=self.today.strftime('%Y-%m'))
        with self.assertRaises(UserError):award.action_submit_approval()
        award.approval_line_ids=[Command.clear(),Command.create({'user_id':self.executive.id})]
        self._complete(award,self.executive)
        self.assertEqual(plan.quality_activity_award_count,1)
    def test_improvement_and_plan_department_are_required(self):
        plan=self._plan();plan.with_user(self.executive).action_approve()
        activity=self._activity(plan,improvement_type='behavior')
        with self.assertRaises(UserError):activity.action_submit_approval()
        activity.improvement_note='SYNTHETIC reinforce work standard'
        self._complete(activity)
