from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestPqcClosePolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.a, cls.b = cls.env['res.company'].create([
            {'name': 'SYNTHETIC PQC policy A'}, {'name': 'SYNTHETIC PQC policy B'}])
        cls.author = new_test_user(cls.env, login='pqc_policy_author',
            groups='base.group_user,iatf_process_inspection.group_process_inspection_user',
            email='pqc-author@example.invalid', company_id=cls.a.id,
            company_ids=[Command.set((cls.a | cls.b).ids)])
        cls.manager = new_test_user(cls.env, login='pqc_policy_manager',
            groups='base.group_user,iatf_process_inspection.group_process_inspection_manager',
            email='pqc-manager@example.invalid', company_id=cls.a.id,
            company_ids=[Command.set((cls.a | cls.b).ids)])
        cls.decider = new_test_user(cls.env, login='pqc_policy_decider',
            groups='base.group_user,cams_ops_process.group_policy_ceo',
            email='pqc-decider@example.invalid', company_id=cls.a.id,
            company_ids=[Command.set((cls.a | cls.b).ids)])
        cls.product = cls.env['product.product'].create({'name': 'SYNTHETIC PQC policy part'})
        cls.env['iatf.approval.policy']._sync_documents()
        cls.env['iatf.approval.policy'].search([('model', '=', 'iatf.process.inspection')]).write({
            'require_rule': False, 'lock_lines': False})
        cls.env['iatf.approval.template'].search(['|', ('model_id', '=', False),
            ('model_id.model', '=', 'iatf.process.inspection')]).write({'active': False})

    def policy(self, company=None):
        company = self.a if company is None else company
        return self.env['ops.policy'].with_user(self.decider).with_context(
            allowed_company_ids=[company.id]).search([('key', '=', 'pqc.close_approval')])

    def inspection(self, company=None, **values):
        company = self.a if company is None else company
        record = self.env['iatf.process.inspection'].with_user(self.author).with_context(
            allowed_company_ids=[company.id], no_reset_password=True).create(dict({
                'company_id': company.id, 'product_id': self.product.id,
                'quantity_produced': 1, 'quantity_inspected': 1, 'quantity_accepted': 1,
                'result': 'pass', 'line_ids': [Command.create({'characteristic_name': 'Synthetic visual',
                    'specification': 'No crack', 'measured_value': 'No crack', 'result': 'pass'})],
            }, **values))
        record.action_decide()
        return record

    def approve(self, record):
        record.approval_line_ids = [Command.create({'user_id': self.manager.id})]
        record.action_submit_approval()
        record.with_user(self.manager).action_approve_approval()
        return record.approval_request_id

    def attachment(self, record):
        attachment = self.env['ir.attachment'].with_user(self.author).create({
            'name': 'SYNTHETIC evidence.txt', 'raw': b'original', 'res_model': record._name,
            'res_id': record.id, 'company_id': record.company_id.id})
        record.attachment_ids = [Command.link(attachment.id)]
        return attachment

    def test_default_is_recorded_decision_and_repeat_seed_preserves_new_choice(self):
        policy = self.policy()
        self.assertEqual((policy.state, policy.value), ('decided', 'none'))
        self.assertIn('설치 실행자', policy.decision_note)
        policy.write({'value': 'reapprove'})
        before = (policy.value, policy.decided_by, policy.decided_at, policy.write_date)
        self.env['ops.policy']._seed_registered(self.a)
        self.assertEqual((policy.value, policy.decided_by, policy.decided_at, policy.write_date), before)
        with self.assertRaises(AccessError):
            self.env['ops.policy'].with_user(self.decider)._seed_registered(self.a)

    def test_none_keeps_pass_close_without_approval(self):
        record = self.inspection()
        record.action_close()
        self.assertEqual(record.state, 'closed')
        self.assertFalse(record.pqc_closure_basis)

    def test_required_rejects_unapproved_then_closes_with_immutable_basis(self):
        self.policy().write({'value': 'required'})
        record = self.inspection()
        with self.assertRaises(UserError):
            record.action_close()
        request = self.approve(record)
        record.action_close()
        self.assertEqual((record.state, record.approval_state), ('closed', 'approved'))
        self.assertEqual(record.pqc_closure_basis['request_id'], request.id)
        self.assertEqual(request.state, 'approved')
        with self.assertRaises(UserError):
            record.write({'pqc_closure_basis': {}})

    def test_required_keeps_common_edit_reset(self):
        self.policy().write({'value': 'required'})
        record = self.inspection()
        previous = self.approve(record)
        record.notes = 'Synthetic revised note'
        self.assertEqual(previous.state, 'approved')
        self.assertEqual(record.approval_state, 'draft')
        with self.assertRaises(UserError):
            record.action_close()

    def test_reapprove_detects_attachment_drift_and_accepts_new_revision(self):
        self.policy().write({'value': 'reapprove'})
        record = self.inspection()
        attachment = self.attachment(record)
        previous = self.approve(record)
        original_snapshot = dict(previous.snapshot)
        attachment.write({'raw': b'corrected evidence'})
        self.assertEqual(record.approval_state, 'approved')
        with self.assertRaisesRegex(UserError, '상신 이후'):
            record.action_close()
        record.action_reset_approval()
        record.action_submit_approval()
        record.with_user(self.manager).action_approve_approval()
        record.action_close()
        self.assertEqual(record.state, 'closed')
        self.assertNotEqual(record.approval_request_id, previous)
        self.assertEqual(previous.state, 'approved')
        self.assertEqual(previous.snapshot, original_snapshot)
        self.assertNotEqual(previous.snapshot['pqc'], record.approval_request_id.snapshot['pqc'])

    def test_required_does_not_claim_attachment_content_reapproval(self):
        self.policy().write({'value': 'required'})
        record = self.inspection()
        attachment = self.attachment(record)
        self.approve(record)
        attachment.write({'raw': b'updated related content'})
        record.action_close()
        self.assertEqual(record.pqc_closure_basis['policy'], 'required')

    def test_reapprove_unchanged_and_direct_request_submit_path(self):
        self.policy().write({'value': 'reapprove'})
        record = self.inspection()
        record.approval_line_ids = [Command.create({'user_id': self.manager.id})]
        record.approval_request_id.action_submit()
        record.with_user(self.manager).action_approve_approval()
        record.action_close()
        self.assertEqual(record.pqc_closure_basis['policy'], 'reapprove')

    def test_actual_company_policy_and_unauthorized_company(self):
        self.policy(self.a).write({'value': 'required'})
        record = self.inspection(self.a).with_context(allowed_company_ids=[self.b.id, self.a.id])
        self.assertEqual(record.env.company, self.b)
        with self.assertRaises(UserError):
            record.action_close()
        with self.assertRaises(AccessError):
            record.with_context(allowed_company_ids=[self.b.id]).action_close()
        self.assertEqual(record.state, 'decided')

    def test_no_direct_create_combined_write_or_context_snapshot_bypass(self):
        self.policy().write({'value': 'required'})
        record = self.inspection()
        with self.assertRaises(UserError), self.cr.savepoint():
            record.copy({'state': 'closed'})
        with self.assertRaises(UserError):
            record.with_context(_pqc_close_service=True).write({'pqc_closure_basis': {}})
        self.approve(record)
        with self.assertRaises(UserError):
            record.write({'state': 'closed', 'notes': 'change at closure'})
        self.assertEqual(record.state, 'decided')

    def test_reapproval_never_unlocks_source_or_self_approval(self):
        self.policy().write({'value': 'reapprove'})
        record = self.inspection()
        with self.assertRaises(UserError):
            record.quantity_accepted = 9
        record.approval_line_ids = [Command.create({'user_id': self.author.id})]
        with self.assertRaises(UserError):
            record.action_submit_approval()
        self.assertNotEqual(record.approval_state, 'approved')

    def test_policy_change_does_not_rewrite_closed_history(self):
        self.policy().write({'value': 'reapprove'})
        record = self.inspection()
        self.approve(record)
        record.action_close()
        before = dict(record.pqc_closure_basis)
        self.policy().write({'value': 'none'})
        self.assertEqual(record.pqc_closure_basis, before)
        self.assertEqual(record.state, 'closed')
