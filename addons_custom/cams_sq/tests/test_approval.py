import base64
from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged('post_install', '-at_install')
class TestSqApproval(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()
        cls.standard = cls.env['sq.standard'].search([
            ('sector', '=', 'INJ'), ('company_id', '=', cls.env.company.id)], limit=1)
        cls.author = new_test_user(cls.env, login='sq_snapshot_author',
            groups='cams_sq.group_sq_manager,iatf_audit.group_audit_manager',
            email='sq-author@example.invalid')
        cls.approver = new_test_user(cls.env, login='sq_snapshot_approver',
            groups='cams_sq.group_sq_user', email='sq-approver@example.invalid')

    def assessment(self):
        audit = self.env['iatf.audit'].with_user(self.author).create({
            'title': 'SQ 승인 내용 보존 시험', 'audit_type': 'sq',
            'planned_date': fields.Date.today(), 'lead_auditor_id': self.author.id,
            'company_id': self.env.company.id, 'sq_standard_id': self.standard.id,
            'sq_date_from': '2026-10-23', 'sq_date_to': '2026-10-23',
            'approval_line_ids': [(0, 0, {'user_id': self.approver.id})],
        })
        audit.action_sq_initialize()
        audit.action_start()
        audit.sq_line_ids.write({'rating': 'partial', 'reason': '시험용 근거: 실제 적합 판정 아님'})
        return audit

    def approve(self, audit):
        audit.action_submit_approval()
        audit.with_user(self.approver).action_approve_approval()
        self.assertEqual(audit.approval_state, 'approved')
        return audit.approval_request_id

    def test_publish_followup_close_keep_same_approval(self):
        audit = self.assessment()
        request = self.approve(audit)
        snapshot = request.snapshot
        audit.action_issue_report()
        audit.action_follow_up()
        audit.action_close()
        self.assertEqual(audit.state, 'closed')
        self.assertEqual(audit.approval_request_id, request)
        self.assertEqual(audit.approval_state, 'approved')
        self.assertEqual(request.snapshot, snapshot)
        with self.assertRaises(UserError):
            audit.action_reset_approval()

    def test_attachment_change_after_submission_requires_resubmission(self):
        audit = self.assessment()
        attachment = self.env['ir.attachment'].with_user(self.author).create({
            'name': 'SYNTHETIC-evidence.txt', 'datas': base64.b64encode(b'before'),
            'res_model': 'iatf.audit', 'res_id': audit.id})
        audit.attachment_ids = attachment
        audit.action_submit_approval()
        attachment.write({'datas': base64.b64encode(b'after')})
        with self.assertRaises(UserError):
            audit.with_user(self.approver).action_approve_approval()
        self.assertEqual(audit.approval_state, 'in_progress')

    def test_publish_requires_approval_and_no_forged_state(self):
        audit = self.assessment()
        with self.assertRaises(UserError):
            audit.action_issue_report()
        with self.assertRaises(UserError):
            audit.with_context(_sq_transition=True).write({'state': 'report'})
        with self.assertRaises(UserError):
            audit.action_close()
        self.assertEqual(audit.state, 'in_progress')

    def test_child_change_revises_pending_and_approved_requests(self):
        for approved in (False, True):
            audit = self.assessment()
            audit.action_submit_approval()
            if approved:
                audit.with_user(self.approver).action_approve_approval()
            old = audit.approval_request_id
            snapshot = old.snapshot
            audit.sq_line_ids[0].write({'reason': '보완된 새로운 근거'})
            self.assertNotEqual(audit.approval_request_id, old)
            self.assertEqual(audit.approval_request_id.previous_request_id, old)
            self.assertEqual(audit.approval_state, 'draft')
            self.assertEqual(old.snapshot, snapshot)
            with self.assertRaises(UserError):
                audit.action_issue_report()
            self.approve(audit)
            audit.action_issue_report()

    def test_reject_resubmit_preserves_snapshots(self):
        audit = self.assessment()
        audit.action_submit_approval()
        old = audit.approval_request_id
        audit.with_user(self.approver).action_reject_approval()
        audit.sq_line_ids[0].write({'reason': '반려 보완'})
        self.approve(audit)
        self.assertEqual(old.state, 'rejected')
        self.assertEqual(audit.approval_request_id.previous_request_id, old)
        audit.action_issue_report()

    def test_self_approval_rejected_and_snapshot_cannot_be_written(self):
        audit = self.assessment()
        audit.write({'approval_line_ids': [(5, 0, 0), (0, 0, {'user_id': self.author.id})]})
        with self.assertRaises(UserError):
            audit.action_submit_approval()
        with self.assertRaises(UserError):
            audit.approval_request_id.write({'snapshot': {'sq': {'digest': audit._sq_content_digest()}}})

    def test_published_content_locked_and_revision_has_new_approval(self):
        audit = self.assessment()
        request = self.approve(audit)
        audit.action_issue_report()
        for values in [{'title': '덮어쓰기'}, {'audit_report': '<p>내용 교체</p>'},
                       {'sq_date_to': '2026-10-24'}, {'company_id': self.env.company.id}]:
            with self.assertRaises(UserError):
                audit.write(values)
        with self.assertRaises(UserError):
            audit.sq_line_ids[0].write({'rating': 'good'})
        action = audit.action_sq_revise()
        revised = audit.browse(action['res_id'])
        self.assertEqual(revised.sq_revision_of_id, audit)
        self.assertEqual(revised.state, 'planned')
        self.assertEqual(revised.approval_state, 'draft')
        self.assertNotEqual(revised.approval_request_id, request)
        self.assertEqual(audit.approval_request_id, request)
        self.assertTrue(all(not line.evidence_snapshot for line in revised.sq_line_ids))

    def test_findings_cannot_change_approved_content_but_can_close(self):
        audit = self.assessment()
        finding = self.env['iatf.audit.finding'].with_user(self.author).create({
            'audit_id': audit.id, 'finding_type': 'observation', 'description': '현장 확인 필요'})
        request = self.approve(audit)
        audit.action_issue_report()
        with self.assertRaises(UserError):
            finding.write({'description': '승인 내용 교체'})
        with self.assertRaises(UserError):
            audit.action_close()
        finding.write({'closure_notes': '독립 확인 완료'})
        finding.action_close()
        audit.action_close()
        self.assertEqual(audit.approval_request_id, request)

    def test_ordinary_audit_keeps_existing_workflow(self):
        audit = self.env['iatf.audit'].with_user(self.author).create({
            'title': '일반 IATF 회귀', 'planned_date': fields.Date.today(),
            'lead_auditor_id': self.author.id})
        audit.action_start()
        audit.action_issue_report()
        self.assertEqual(audit.state, 'report')
