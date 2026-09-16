from odoo.exceptions import AccessError, UserError
from odoo.tests.common import new_test_user, tagged

from .test_integrity import IntegrityCase


@tagged('post_install', '-at_install')
class TestApprovalManagement(IntegrityCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='approval_scope_manager', groups='pumui_approval.group_pumui_manager')
        cls.peer = new_test_user(cls.env, login='approval_scope_peer', groups='pumui_approval.group_pumui_user')

    def test_manager_can_manage_draft_but_only_assigned_user_can_approve(self):
        p = self._request(approve=False).with_user(self.manager)
        self.assertTrue(p.approval_request_id.can_manage)
        self.assertIn(p.approval_request_id, self.env['iatf.approval.request'].with_user(self.manager).search([]))
        p.approval_line_ids.unlink()
        p.write({'approval_line_ids': [(0, 0, {'user_id': self.approver.id, 'sequence': 1})]})
        p.approval_line_ids.write({'sequence': 5})
        p.action_submit_approval()
        for operation in (p.action_approve_approval, p.approval_request_id.action_reject):
            with self.assertRaises(UserError), self.cr.savepoint():
                operation()
        p.with_user(self.approver).action_approve_approval()
        self.assertEqual(p.approval_state, 'approved')

    def test_author_can_remove_and_replace_draft_line(self):
        p = self._request(approve=False)
        p.approval_line_ids.unlink()
        p.write({'approval_line_ids': [(0, 0, {'user_id': self.approver.id})]})
        self.assertEqual(p.approval_line_ids.user_id, self.approver)

    def test_unrelated_writer_has_no_approval_management_access(self):
        p = self._request(approve=False)
        p.with_user(self.peer).check_access('write')
        request = p.approval_request_id.with_user(self.peer)
        self.assertFalse(request.search([('id', '=', request.id)]))
        for operation in (
            lambda: request.read(['snapshot']),
            lambda: p.with_user(self.peer).write({'approval_line_ids': [(0, 0, {'user_id': self.peer.id})]}),
            lambda: p.approval_line_ids.with_user(self.peer).unlink(),
        ):
            with self.assertRaises(AccessError), self.cr.savepoint():
                operation()

    def test_manager_cannot_edit_decisions_or_non_draft_lines(self):
        p = self._request(approve=False).with_user(self.manager)
        p.action_submit_approval()
        for state in ('in_progress', 'approved'):
            if state == 'approved':
                p.with_user(self.approver).action_approve_approval()
            for operation in (
                lambda: p.approval_line_ids.write({'user_id': self.manager.id}),
                p.approval_line_ids.unlink,
                lambda: self.env['iatf.approval.line'].with_user(self.manager).create({'request_id': p.approval_request_id.id, 'user_id': self.manager.id}),
                lambda: self.env['iatf.approval.line'].with_user(self.manager).with_context(default_request_id=p.approval_request_id.id).create({'user_id': self.manager.id}),
            ):
                with self.assertRaises(UserError), self.cr.savepoint():
                    operation()
            with self.assertRaises(AccessError), self.cr.savepoint():
                p.approval_line_ids.write({'state': 'approved'})

    def test_manager_reset_preserves_history(self):
        p = self._request().with_user(self.manager)
        old = p.approval_request_id
        p.action_reset_approval()
        self.assertEqual(p.approval_state, 'draft')
        self.assertEqual(old.state, 'approved')
        self.assertEqual(p.approval_request_id.previous_request_id, old)
        p.approval_line_ids.unlink()
        p.write({'approval_line_ids': [(0, 0, {'user_id': self.author.id})]})
        self.assertEqual(old.line_ids.user_id, self.approver)

    def test_other_company_and_revoked_manager_access_are_denied(self):
        p = self._request(approve=False)
        company = self.env['res.company'].create({'name': 'Approval other company'})
        other = self.env['pumui.request'].with_company(company).create({
            'title': 'Other company scope', 'partner_id': self.partner.id, 'company_id': company.id})
        requests = self.env['iatf.approval.request'].with_user(self.manager)
        self.assertTrue(requests.search([('id', '=', p.approval_request_id.id)]))
        self.assertFalse(requests.search([('id', '=', other.approval_request_id.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            other.with_user(self.manager).write({'approval_line_ids': [(0, 0, {'user_id': self.manager.id})]})
        self.manager.groups_id = self.env.ref('pumui_approval.group_pumui_user')
        self.assertFalse(requests.search([('id', '=', p.approval_request_id.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.approval_request_id.with_user(self.manager).read(['snapshot'])

    def test_document_record_rules_limit_delegation(self):
        p = self._request(approve=False)
        requests = self.env['iatf.approval.request'].with_user(self.manager)
        self.assertTrue(requests.search([('id', '=', p.approval_request_id.id)]))
        self.env['ir.rule'].create({
            'name': 'Approval scope test',
            'model_id': self.env['ir.model']._get_id('pumui.request'),
            'domain_force': "[('id', '!=', %s)]" % p.id,
        })
        self.assertFalse(requests.search([('id', '=', p.approval_request_id.id)]))
        with self.assertRaises(AccessError), self.cr.savepoint():
            p.with_user(self.manager).action_submit_approval()
