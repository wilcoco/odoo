from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestChangeWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        roles = 'iatf_change_management.group_change_management_'
        cls.author = new_test_user(cls.env, login='change_author', groups=roles + 'user', email='change-author@example.invalid')
        cls.reviewer = new_test_user(cls.env, login='change_reviewer', groups=roles + 'user', email='change-review@example.invalid')
        cls.manager = new_test_user(cls.env, login='change_manager', groups=roles + 'manager', email='change-manager@example.invalid')
        cls.verifier = new_test_user(cls.env, login='change_verifier', groups=roles + 'user', email='change-verify@example.invalid')

    def request(self):
        return self.env['iatf.change.request'].with_user(self.author).create({
            'title': 'SYNTHETIC 4M 승인 흐름', 'change_type': 'method',
            'description': '<p>시험 변경</p>', 'reason': '<p>독립 승인 경계 검증</p>',
            'reviewer_id': self.reviewer.id, 'verification_owner_id': self.verifier.id,
            'approval_line_ids': [Command.create({'user_id': self.manager.id})],
        })

    def approve(self, record):
        record.action_request()
        record.with_user(self.reviewer).action_review()
        record.action_submit_approval()
        record.with_user(self.manager).action_approve_approval()
        record.with_user(self.manager).action_approve()

    def test_independent_approval_and_verification_keep_evidence(self):
        record = self.request()
        self.approve(record)
        evidence = record.approval_request_id
        snapshot = evidence.snapshot
        self.assertEqual(record.approved_by, self.manager)
        record.with_user(self.manager).action_implement()
        with self.assertRaises(UserError):
            record.action_verify()
        with self.assertRaises(UserError):
            record.with_user(self.manager).action_verify()
        record.with_user(self.verifier).action_verify()
        record.with_user(self.verifier).write({'verification_result': '<p>독립 검증</p>', 'effective': 'yes'})
        record.with_user(self.verifier).action_close()
        self.assertEqual(record.state, 'closed')
        self.assertEqual(record.approval_state, 'approved')
        self.assertEqual(record.approval_request_id, evidence)
        self.assertEqual(evidence.snapshot, snapshot)
        with self.assertRaises(UserError):
            record.action_reset_approval()

    def test_self_review_approval_and_out_of_order_are_rejected(self):
        record = self.request()
        with self.assertRaises(UserError):
            record.with_user(self.manager).action_approve()
        with self.assertRaises(UserError):
            record.action_submit_approval()
        record.action_request()
        with self.assertRaises(UserError):
            record.action_review()
        record.with_user(self.reviewer).action_review()
        record.write({'approval_line_ids': [Command.clear(), Command.create({'user_id': self.author.id})]})
        with self.assertRaises(UserError):
            record.action_submit_approval()

    def test_direct_state_and_audit_stamp_forgery_are_rejected(self):
        record = self.request()
        for values in ({'state': 'approved'}, {'approved_by': self.manager.id}, {'requested_by': self.manager.id}):
            with self.assertRaises(UserError):
                record.with_context(_change_workflow=True).write(values)
        with self.assertRaises(UserError):
            record.with_context(default_approved_by=self.manager.id).create({
                'title': 'SYNTHETIC forged', 'change_type': 'method', 'description': 'x', 'reason': 'x'})

    def test_reviewed_content_locked_and_rejection_creates_revision(self):
        record = self.request()
        record.action_request()
        record.with_user(self.reviewer).action_review()
        record.action_submit_approval()
        old = record.approval_request_id
        with self.assertRaises(UserError):
            record.write({'description': '<p>승인 중 변경</p>'})
        record.with_user(self.manager).action_reject_approval()
        self.assertEqual(record.state, 'rejected')
        record.action_change_reset_draft()
        record.write({'description': '<p>반려 보완</p>'})
        self.approve(record)
        self.assertEqual(old.state, 'rejected')
        self.assertEqual(record.approval_request_id.previous_request_id, old)

    def test_request_needs_assigned_independent_reviewer(self):
        record = self.request()
        record.reviewer_id = self.author
        with self.assertRaises(UserError):
            record.action_request()

    def test_customer_approval_and_verifier_are_required(self):
        record = self.request()
        record.write({'customer_notification_required': True, 'customer_approval': 'pending'})
        record.action_request()
        record.with_user(self.reviewer).action_review()
        record.action_submit_approval()
        record.with_user(self.manager).action_approve_approval()
        with self.assertRaises(UserError):
            record.with_user(self.manager).action_approve()
        other = self.request()
        self.approve(other)
        other.with_user(self.manager).action_implement()
        other.with_user(self.verifier).action_verify()
        other.write({'verification_result': '확인', 'effective': 'yes'})
        with self.assertRaises(UserError):
            other.with_user(self.manager).action_close()
