from datetime import timedelta
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestPreassessment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author = new_test_user(cls.env, login='p1-qualification-author', groups='iatf_training.group_training_user,iatf_document_control.group_document_user')
        cls.reviewer = new_test_user(cls.env, login='p1-qualification-reviewer', groups='iatf_training.group_training_manager,iatf_document_control.group_document_manager,iatf_change_management.group_change_management_user')
        cls.employee = cls.env['hr.employee'].create({'name': 'SYNTHETIC assessment employee', 'company_id': cls.env.company.id})
        cls.matrix = cls.env['iatf.competence.matrix'].create({'employee_id': cls.employee.id, 'skill_name': 'SYNTHETIC setup', 'required_level': '3', 'current_level': '1'})
        cls.today = fields.Date.today()
        cls.category = cls.env['iatf.document.category'].create({'name': 'SYNTHETIC assessment criterion', 'code': 'P1-QUAL'})

    def _record(self):
        criteria = self.env['iatf.document'].with_user(self.author).create({
            'name': 'SYNTHETIC qualification criteria', 'category_id': self.category.id,
            'owner_id': self.author.id, 'reviewer_id': self.reviewer.id, 'approver_id': self.reviewer.id,
            'quality_evidence_kind': 'qualification_criteria',
            'quality_valid_from': self.today-timedelta(days=1), 'quality_valid_until': self.today+timedelta(days=30),
            'qualification_criteria_confirmed': True, 'qualification_theory_min': 70,
            'qualification_practical_min': 80, 'qualification_method': 'SYNTHETIC actual observation checklist'})
        criteria.action_submit_review(); criteria.with_user(self.reviewer).action_approve()
        report = self.env['ir.attachment'].with_user(self.author).create({'name': 'SYNTHETIC assessment.txt', 'raw': b'SYNTHETIC test report'})
        return self.env['iatf.qualification.preassessment'].with_user(self.author).create({
            'name': 'SYNTHETIC preassessment', 'competence_id': self.matrix.id, 'criteria_document_id': criteria.id,
            'trace_exception': 'SYNTHETIC training room without production LOT',
            'theory_score': 90, 'practical_score': 90, 'assessed_level': '3', 'observation': 'SYNTHETIC practical observations',
            'result': 'pass', 'attachment_ids': [Command.link(report.id)],
            'approval_line_ids': [Command.create({'user_id': self.reviewer.id})]})

    def _complete(self, record):
        record.action_submit_approval()
        record.with_user(self.reviewer).action_approve_approval()
        record.action_complete_evidence()

    def test_approved_assessment_does_not_promote_employee_and_keeps_revision(self):
        record = self._record(); self._complete(record)
        self.assertEqual(self.matrix.current_level, '1')
        before = record.completion_snapshot
        self.matrix.current_level = '2'
        self.assertEqual(record.completion_snapshot, before)
        self.assertEqual(before['competence']['current_level'], '1')
        with self.assertRaises(UserError): record.theory_score = 100
        with self.assertRaises(UserError): record.attachment_ids.write({'raw': b'changed'})
        new = self.env[record._name].with_user(self.author).browse(record.action_new_evidence_revision()['res_id'])
        self.assertEqual(new.evidence_revision, 2)
        self.assertFalse(new.completion_snapshot)

    def test_failed_score_requires_followup_and_cannot_pass(self):
        record = self._record(); record.practical_score = 40
        with self.assertRaises(UserError): record.action_submit_approval()
        record.result = 'fail'
        with self.assertRaises(UserError): record.action_submit_approval()
        record.followup = 'SYNTHETIC retraining before reassessment'
        self._complete(record)
        self.assertEqual(record.result, 'fail')
        self.assertEqual(self.matrix.current_level, '1')

    def test_cross_company_and_pending_basis_change(self):
        other = self.env['res.company'].create({'name': 'SYNTHETIC assessment company'})
        employee = self.env['hr.employee'].create({'name': 'SYNTHETIC other employee', 'company_id': other.id})
        matrix = self.env['iatf.competence.matrix'].create({'employee_id': employee.id, 'skill_name': 'SYNTHETIC private competence'})
        with self.assertRaises(AccessError): matrix.with_user(self.author).read(['skill_name'])
        record = self._record(); record.action_submit_approval()
        self.matrix.required_level = '4'
        with self.assertRaises(UserError): record.with_user(self.reviewer).action_approve_approval()
