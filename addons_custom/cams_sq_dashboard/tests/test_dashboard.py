from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError
from odoo import fields


@tagged('post_install','-at_install')
class TestDashboard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()

    def test_dashboard_two_sectors_no_fake_pass(self):
        data=self.env['iatf.sq.dashboard'].get_dashboard_data('2099-01-01','2099-01-31')
        self.assertEqual(len(data['sectors']),2)
        self.assertTrue(all(r['points']==1000 for r in data['sectors']))
        self.assertTrue(all(r['inspection_rate'] is None for r in data['boards']))
        self.assertTrue(all(r['ready']==0 for r in data['sectors']))

    def test_dashboard_bad_period_rejected(self):
        with self.assertRaises(UserError):
            self.env['iatf.sq.dashboard'].get_dashboard_data('2026-12-31','2026-01-01')

    def test_source_action_allowlist(self):
        with self.assertRaises(UserError):
            self.env['iatf.sq.dashboard'].open_records('res.users','2026-01-01','2026-12-31')

    def test_sq_ops_guards_and_regular_ops_preserved(self):
        role=self.env['ops.role'].create({'name':'SQ 시험 역할'})
        regular=self.env['ops.task.def'].create({'name':'기존 업무 시험','role_id':role.id,'periodicity':'adhoc','requires_approval':False})
        task=regular._create_task('SQ-REGULAR-TEST',fields.Date.today())
        task.action_mark_done()
        self.assertEqual(task.state,'approved')
        item=self.env['sq.item'].search([('company_id','=',self.env.company.id)],limit=1)
        definition=self.env['ops.task.def'].create({'name':'SQ 시험 업무','role_id':role.id,'periodicity':'adhoc','sq_item_id':item.id,'requires_approval':True})
        sqtask=definition._create_task('SQ-GUARD-TEST',fields.Date.today())
        with self.assertRaises(UserError):sqtask.write({'state':'approved'})
        with self.assertRaises(UserError):sqtask.action_mark_done()

    def test_sq_menu_below_independent_root(self):
        menu=self.env.ref('cams_sq_dashboard.menu_sq_dashboard')
        self.assertEqual(menu.parent_id.parent_id,self.env.ref('cams_sq.menu_sq_root'))
