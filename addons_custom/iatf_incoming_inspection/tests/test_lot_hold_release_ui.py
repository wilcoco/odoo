from lxml import etree
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools.safe_eval import safe_eval
from .hold_release_fixture import make_policy, request_values


@tagged('post_install', '-at_install')
class TestLotHoldReleaseUi(TransactionCase):
    """The real get_view arch and existing approval methods, no browser simulation claim."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.policy, cls.quality, cls.production = make_policy(cls.env, 'release_ui')
        cls.stock = new_test_user(cls.env, login='release_ui_stock', groups='stock.group_stock_user',
            company_id=cls.env.company.id, company_ids=[Command.set(cls.env.company.ids)])
        cls.product = cls.env['product.product'].create({'name': 'Synthetic release UI material',
            'is_storable': True, 'tracking': 'lot'})
        cls.view_id = cls.env.ref('iatf_incoming_inspection.lot_hold_release_form').id

    def setUp(self):
        super().setUp()
        self.lot = self.env['stock.lot'].create({'name': self._testMethodName,
            'product_id': self.product.id, 'company_id': self.env.company.id,
            'quality_hold': True, 'hold_reason': 'SYNTHETIC independent hold'})
        self.rec = self.env['iatf.lot.hold.release'].with_user(self.stock).create(request_values(self.lot))

    def _arch(self, user):
        result = self.rec.with_user(user).get_view(view_id=self.view_id, view_type='form')
        return etree.fromstring(result['arch'])

    def _visible(self, user):
        rec = self.rec.with_user(user)
        rec.read(['approval_state', 'approval_current_approver_id', 'approval_line_ids',
                  'released_by', 'released_at'])
        rec.approval_line_ids.read(['sequence', 'user_id', 'state', 'action_date', 'note'])
        values = {field: rec[field] for field in ('approval_state', 'approval_is_current_user',
                  'release_state', 'release_snapshot')}
        return {button.get('name') for button in self._arch(user).xpath('//header/button')
                if not safe_eval(button.get('invisible', 'False'), values)}

    def _assert_visible(self, stock, quality, production):
        # All four reads share this transaction's cache. Returning to stock also
        # proves a prior approver's cached True does not leak back to the author.
        for user, expected in ((self.stock, stock), (self.quality, quality),
                               (self.production, production), (self.stock, stock)):
            self.assertEqual(self._visible(user), set(expected), user.login)

    def _approve_from_view(self, user):
        rec = self.rec.with_user(user)
        arch = self._arch(user)
        button = arch.xpath("//button[@name='action_approve_approval']")[0]
        displayed = rec.approval_current_line_id.id
        context = safe_eval(button.get('context'), {'approval_current_line_id': displayed})
        self.assertEqual(context, {'approval_expected_line_id': displayed})
        rec.with_context(**context).action_approve_approval()

    def test_form_supports_stock_submit_two_role_approvals_and_explicit_release(self):
        self._assert_visible(['action_submit_approval'], ['action_submit_approval'], ['action_submit_approval'])
        self.rec.action_submit_approval()
        self._assert_visible([], ['action_approve_approval', 'action_reject_approval'], [])
        self._approve_from_view(self.quality)
        self.assertTrue(self.lot.quality_hold)
        self._assert_visible([], [], ['action_approve_approval', 'action_reject_approval'])
        self._approve_from_view(self.production)
        self.assertTrue(self.lot.quality_hold)
        self._assert_visible([], [], ['action_release_hold'])
        self.rec.with_user(self.production).action_release_hold()
        self.assertFalse(self.lot.quality_hold)
        self.assertEqual(self.rec.release_state, 'executed')
        self.assertEqual(self.rec.released_by, self.production)
        self.assertTrue(self.rec.released_at)
        self.assertEqual(self.rec.approval_line_ids.mapped('state'), ['approved', 'approved'])
        self.assertTrue(all(self.rec.approval_line_ids.mapped('action_date')))
        self._assert_visible([], [], [])

    def test_rejected_form_keeps_history_and_requires_new_request(self):
        self.rec.action_submit_approval()
        old_request = self.rec.approval_request_id
        self.rec.with_user(self.quality).action_reject_approval()
        self._assert_visible([], [], [])
        self.assertEqual(old_request.state, 'rejected')
        self.assertTrue(self.lot.quality_hold)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.rec.action_submit_approval()
        self.rec = self.env['iatf.lot.hold.release'].with_user(self.stock).create(request_values(self.lot))
        self._assert_visible(['action_submit_approval'], ['action_submit_approval'], ['action_submit_approval'])
        self.rec.action_submit_approval()
        self.assertNotEqual(self.rec.approval_request_id, old_request)
        self.assertEqual(old_request.state, 'rejected')

    def test_history_readable_but_line_and_policy_not_editable_by_roles(self):
        self.rec.action_submit_approval()
        for user in (self.stock, self.quality, self.production):
            arch = self._arch(user)
            history = arch.xpath("//field[@name='approval_line_ids']")[0]
            self.assertEqual(history.get('readonly'), '1')
            for operation in ('create', 'edit', 'delete'):
                self.assertEqual(history.find('list').get(operation), '0')
            self.assertTrue(arch.xpath("//field[@name='approval_current_approver_id']"))
            self.assertFalse(self.policy.with_user(user).has_access('write'))
            self.policy.with_user(user).read(['company_id', 'quality_user_id', 'production_user_id'])
            with self.assertRaises(UserError), self.env.cr.savepoint():
                self.rec.with_user(user).approval_line_ids[:1].write({'state': 'approved'})
        stock_arch = self._arch(self.stock)
        self.assertFalse(stock_arch.xpath("//button[@name='action_release_hold']"))
        self.assertFalse(stock_arch.xpath("//button[@name='action_approve_approval']"))
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            self.rec.with_user(self.stock).action_release_hold()
