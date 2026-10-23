from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from odoo import api, fields, Command
from odoo.tests import TransactionCase, tagged, new_test_user
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError


@tagged('post_install', '-at_install')
class TestOpsPolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manager = new_test_user(cls.env, login='ops_manager', email='manager@example.invalid', groups='base.group_user,hr_holidays.group_hr_holidays_user')
        cls.hr = new_test_user(cls.env, login='ops_hr', email='hr@example.invalid', groups='base.group_user,hr_holidays.group_hr_holidays_manager')
        cls.worker = new_test_user(cls.env, login='ops_worker', email='worker@example.invalid', groups='base.group_user')
        for user in (cls.manager, cls.hr, cls.worker):
            cls.env['hr.employee'].create({'name':user.name, 'user_id':user.id, 'company_id':cls.env.company.id,
                'resource_calendar_id':cls.env.company.resource_calendar_id.id, 'leave_manager_id':cls.manager.id})
        cls.kind = cls.env['hr.leave.type'].create({'name':'SYNTHETIC Two step', 'requires_allocation':'no', 'leave_validation_type':'both'})

    def _leave(self):
        return self.env['hr.leave'].with_user(self.worker).create({'name':'SYNTHETIC policy leave',
            'employee_id':self.worker.employee_id.id, 'holiday_status_id':self.kind.id,
            'request_date_from':date(2030,1,7), 'request_date_to':date(2030,1,7)})

    def test_policy_company_and_change_reason(self):
        policy = self.env['cams.ops.policy'].create({'change_reason':'SYNTHETIC initial decision'})
        with self.assertRaises(AccessError):
            policy.with_user(self.worker).write({'statement_link_days':10,'change_reason':'unauthorized'})
        with self.assertRaises(ValidationError):
            policy.write({'statement_link_days':10})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            policy.write({'cr_sequence_enforce':False,'change_reason':'attempt bypass'})
        policy.write({'statement_link_days':30,'change_reason':'approved 30 days'})
        self.assertEqual(policy._value(self.env.company,'statement_link_days'),30)

    def test_two_step_no_hr_skip_and_no_rpc_forgery(self):
        leave = self._leave()
        with self.assertRaises(UserError):
            leave.with_user(self.hr).action_validate(check_state=False)
        with self.assertRaises(UserError):
            leave.with_user(self.hr).action_approve(check_state=False)
        with self.assertRaises(UserError):
            leave.with_user(self.hr).with_context(leave_fast_create=True,_ops_leave_transition=True).write({
                'state':'validate', 'first_approver_id':self.manager.employee_id.id})
        leave.with_user(self.manager).action_approve()
        self.assertEqual(leave.state,'validate1')
        with self.assertRaises(UserError):
            leave.with_user(self.manager).action_validate()
        with self.assertRaises(UserError):
            leave.with_user(self.hr).write({'request_date_to':date(2030,1,8)})
        leave.with_user(self.hr).action_validate()
        self.assertEqual(leave.state,'validate')
        self.assertEqual(leave.first_approver_id,self.manager.employee_id)
        self.assertEqual(leave.second_approver_id,self.hr.employee_id)

    def test_email_required_and_approval_template_write_role(self):
        admin = new_test_user(self.env,login='ops_admin',email='admin@example.invalid',groups='base.group_system,base.group_partner_manager')
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.worker.with_user(admin).write({'email':False})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['iatf.approval.template'].create({'name':'SYNTHETIC invalid approver',
                'model_id':self.env['ir.model']._get_id('cams.ops.policy'),
                'line_ids':[(0,0,{'user_id':self.worker.id})]})

    def test_general_scrap_needs_quality_approval_and_preserves_stock_until_execution(self):
        if 'stock.scrap' not in self.env or 'injection_disposition' not in self.env['stock.scrap']._fields:
            self.skipTest('MES disposition integration is not installed')
        quality = new_test_user(self.env,login='ops_quality',email='quality@example.invalid',
            groups='quality.group_quality_manager,stock.group_stock_manager')
        warehouse = self.env['stock.warehouse'].search([('company_id','=',self.env.company.id)],limit=1)
        product = self.env['product.product'].create({'name':'SYNTHETIC general scrap','is_storable':True})
        self.env['stock.quant']._update_available_quantity(product,warehouse.lot_stock_id,2)
        scrap = self.env['stock.scrap'].with_user(quality).create({'product_id':product.id,
            'product_uom_id':product.uom_id.id,'scrap_qty':1,'location_id':warehouse.lot_stock_id.id,
            'injection_disposition':'scrap','injection_disposition_reason':'SYNTHETIC damaged component'})
        with self.assertRaises(UserError):
            scrap.action_validate()
        scrap.action_approve_injection_disposition()
        self.assertEqual(self.env['stock.quant']._get_available_quantity(product,warehouse.lot_stock_id),2)
        scrap.action_validate()
        self.assertEqual(scrap.state,'done')
        self.assertEqual(self.env['stock.quant']._get_available_quantity(product,warehouse.lot_stock_id),1)
        with self.assertRaises(UserError):
            scrap.do_scrap()

    def test_inspection_reference_role_is_read_only(self):
        reader = new_test_user(self.env,login='ops_inspection_reader',email='reader@example.invalid',
            groups='cams_ops_policy.group_inspection_reference')
        for model in ('iatf.control.plan','iatf.control.plan.line','iatf.fmea','iatf.fmea.line'):
            Model = self.env[model].with_user(reader)
            self.assertTrue(Model.has_access('read'))
            self.assertFalse(Model.has_access('write'))
            self.assertFalse(Model.has_access('create'))

    def test_token_coexistence_expiry_and_login_only_policy(self):
        if 'supplier_portal_token' not in self.env['res.partner']._fields:
            self.skipTest('SCM portal is not installed')
        from odoo.addons.supplier_portal_purchase.controllers import portal
        vendor = self.env['res.partner'].create({'name':'SYNTHETIC token supplier','supplier_rank':1,
            'is_supplier_portal':True,'supplier_portal_company_ids':[Command.set(self.env.company.ids)],
            'supplier_portal_token':'test-secret-not-a-real-credential-123456',
            'supplier_portal_token_expiry':fields.Date.today()+timedelta(days=1)})
        req = SimpleNamespace(env=api.Environment(self.cr,self.env.ref('base.public_user').id,
            dict(self.env.context,allowed_company_ids=self.env.company.ids)))
        req.update_env = lambda context=None, **kw: setattr(req,'env',req.env(context=context))
        controller = portal.SupplierPortalController()
        with patch.object(portal,'request',req):
            self.assertEqual(controller._validate_portal_access(vendor.supplier_portal_token).id,vendor.id)
            vendor.supplier_portal_token_expiry = fields.Date.today()-timedelta(days=1)
            with self.assertRaises(AccessDenied):
                controller._validate_portal_access(vendor.supplier_portal_token)
            vendor.supplier_portal_token_expiry = fields.Date.today()+timedelta(days=1)
            self.env['cams.ops.policy'].create({'portal_token_mode':'login','change_reason':'SYNTHETIC login-only check'})
            with self.assertRaises(AccessDenied):
                controller._validate_portal_access(vendor.supplier_portal_token)

    def test_statement_link_30_days_expiry_and_use_once(self):
        if 'transaction.statement' not in self.env:
            self.skipTest('Transaction statements are not installed')
        partner = self.env['res.partner'].create({'name':'SYNTHETIC statement partner'})
        statement = self.env['transaction.statement'].create({'partner_id':partner.id,
            'date_from':fields.Date.today(),'date_to':fields.Date.today()})
        statement._arm_approval_link()
        seconds = (statement.approval_link_expiry-fields.Datetime.now()).total_seconds()
        self.assertAlmostEqual(seconds,30*24*60*60,delta=5)
        statement.approval_link_expiry = fields.Datetime.now()-timedelta(seconds=1)
        self.assertEqual(statement.action_approve_by_link(),'expired')
        self.assertEqual(statement.state,'draft')
        statement._arm_approval_link()
        self.assertEqual(statement.action_approve_by_link(),'approved')
        self.assertEqual(statement.action_approve_by_link(),'used')
