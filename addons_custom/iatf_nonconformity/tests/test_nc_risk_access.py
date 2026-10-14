"""Manual NC registration must not need broad Risk privileges."""
from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestNcRiskAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'iatf.risk.register' not in cls.env:
            from unittest import SkipTest
            raise SkipTest('Install optional iatf_risk to test automatic review integration')
        cls.company = cls.env.company
        cls.other = cls.env['res.company'].create({'name': 'N-NC-RISK other company'})
        ctx = dict(cls.env.context, no_reset_password=True, mail_create_nosubscribe=True,
                   mail_notrack=True, tracking_disable=True, mail_notify_force_send=False)
        cls.env = cls.env(context=ctx)
        cls.nc_user = new_test_user(cls.env, login='nc-risk-author', email='nc@example.test',
            notification_type='inbox', groups='iatf_nonconformity.group_nc_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.owner = new_test_user(cls.env, login='nc-risk-owner', email='risk@example.test',
            notification_type='inbox', groups='iatf_risk.group_risk_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.foreign_owner = new_test_user(cls.env, login='nc-risk-foreign', email='other@example.test',
            notification_type='inbox', groups='iatf_risk.group_risk_user',
            company_id=cls.other.id, company_ids=[Command.set(cls.other.ids)])
        cls.stock_user = new_test_user(cls.env, login='nc-risk-stock', email='stock@example.test',
            notification_type='inbox', groups='stock.group_stock_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.product = cls.env['product.product'].create({'name': 'N-NC-RISK exact product',
                                                       'company_id': cls.company.id})
        cls.match = cls._risk('matching')
        cls.foreign = cls._risk('foreign', company_id=cls.other.id, responsible_id=cls.foreign_owner.id)
        cls.closed = cls._risk('closed', state='closed')
        cls.unrelated = cls._risk('unrelated', description='Different product only')

    @classmethod
    def _risk(cls, title, **vals):
        return cls.env['iatf.risk.register'].create(dict({
            'title': 'N-NC-RISK ' + title, 'description': cls.product.name,
            'company_id': cls.company.id, 'responsible_id': cls.owner.id}, **vals))

    def _nc(self, **vals):
        return self.env['iatf.nonconformity'].with_user(self.nc_user).create(dict({
            'title': 'N-NC-RISK manual source', 'company_id': self.company.id,
            'product_id': self.product.id}, **vals))

    def _activities(self, nc):
        return self.env['mail.activity'].search([('nc_risk_source_id', '=', nc.id)])

    def _risk_values(self):
        return (self.match | self.foreign | self.closed | self.unrelated).read([
            'title', 'description', 'company_id', 'state', 'likelihood', 'impact',
            'risk_score', 'residual_score', 'responsible_id'])

    def _denied(self, call):
        try:
            with self.cr.savepoint():
                call()
        except (AccessError, UserError):
            return
        self.fail('Invalid source must be rejected')

    def test_manual_create_without_risk_role_with_and_without_product(self):
        risks_before = self._risk_values()
        self.assertFalse(self.env['iatf.risk.register'].with_user(self.nc_user).has_access('read'))
        no_product = self._nc(product_id=False)
        self.assertTrue(no_product.exists())
        self.assertFalse(self._activities(no_product))
        nc = self._nc()
        activity = self._activities(nc)
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity.res_model, 'iatf.risk.register')
        self.assertEqual(activity.res_id, self.match.id)
        self.assertEqual(activity.user_id, self.owner)
        self.assertEqual(activity.nc_risk_source_id, nc)
        self.assertEqual(self._risk_values(), risks_before)
        self.assertFalse(self.foreign.activity_ids | self.closed.activity_ids | self.unrelated.activity_ids)
        with self.assertRaises(AccessError):
            self.match.with_user(self.nc_user).read(['description'])

    def test_source_company_and_access_are_checked_before_service(self):
        nc = self._nc(product_id=False)
        with self.assertRaises(AccessError), self.cr.savepoint():
            nc.with_user(self.stock_user)._auto_update_risk()
        self._denied(lambda: self._nc(company_id=self.other.id))
        foreign_product = self.env['product.product'].create({
            'name': 'N-NC-RISK foreign product', 'company_id': self.other.id})
        self._denied(lambda: self._nc(product_id=foreign_product.id))
        self.assertFalse(self.foreign.activity_ids)

    def test_same_named_sources_stay_distinct_and_cannot_forge_activity_links(self):
        first = self._nc(name='N-NC-RISK same name')
        second = self._nc(name='N-NC-RISK same name')
        self.assertNotEqual(first.id, second.id)
        first._auto_update_risk()
        self.assertEqual(len(self._activities(first)), 1)
        self.assertEqual(len(self._activities(second)), 1)
        with self.assertRaises(UserError):
            self._activities(first).write({'nc_risk_source_id': second.id})
        with self.assertRaises(UserError):
            self._activities(first).write({'res_id': self.foreign.id})
        with self.assertRaises(UserError):
            self.env['mail.activity'].with_user(self.nc_user).with_context(
                _nc_risk_activity_service=True, default_nc_risk_source_id=first.id).create({})

    def test_foreign_or_inactive_responsible_gets_nc_followup_not_cross_company_alert(self):
        self.match.responsible_id = self.foreign_owner
        nc = self._nc()
        activity = self._activities(nc)
        self.assertEqual(len(activity), 1)
        self.assertEqual((activity.res_model, activity.res_id), (nc._name, nc.id))
        self.assertEqual(activity.user_id, self.nc_user)
        self.assertFalse(self.match.activity_ids | self.foreign.activity_ids)
        nc._auto_update_risk()
        self.assertEqual(len(self._activities(nc)), 1)
        self.match.responsible_id = self.owner
        self.owner.active = False
        another = self._nc()
        self.assertEqual(self._activities(another).res_model, 'iatf.nonconformity')
        self.assertFalse(self.match.activity_ids | self.foreign.activity_ids)
        self.match.responsible_id = False
        unassigned = self._nc()
        self.assertEqual(self._activities(unassigned).res_model, 'iatf.nonconformity')
        self.assertFalse(self.match.activity_ids | self.foreign.activity_ids)
