from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tests.common import new_test_user
from .test_pp03_pp06 import PlanningCase
from .bom_fixture import injection_bom


@tagged('post_install', '-at_install')
class TestPlanQuantityChange(PlanningCase):
    def setUp(self):
        super().setUp()
        self.manager = new_test_user(self.env, login='plan_qty_manager', groups='injection_planning.group_planning_manager,mrp.group_mrp_manager,stock.group_stock_user', email='plan-manager@example.invalid')
        self.planner = new_test_user(self.env, login='plan_qty_planner', groups='injection_planning.group_planning_user,mrp.group_mrp_user', email='plan-author@example.invalid')
        wc = self._workcenter('QTY-WC')
        mold = self._mold('QTY-MOLD')
        self._cap(wc, mold)
        raw = self.env['product.product'].create({'name': 'SYNTHETIC resin', 'uom_id': self.env.ref('uom.product_uom_kgm').id, 'uom_po_id': self.env.ref('uom.product_uom_kgm').id})
        bom = injection_bom(self.env, {'product_tmpl_id': self.inj.product_tmpl_id.id, 'product_qty': 2,
            'bom_line_ids': [Command.create({'product_id': raw.id, 'product_qty': 1000, 'product_uom_id': self.env.ref('uom.product_uom_gram').id})]})
        run = self._run()
        self.line = self.env['injection.planning.line'].create({
            'planning_run_id': run.id, 'plan_date': self.day, 'workcenter_id': wc.id,
            'mold_id': mold.id, 'product_id': self.inj.id, 'planned_qty': 980})
        self.mo = self.env['mrp.production'].create({
            'product_id': self.inj.id, 'product_qty': 980, 'bom_id': bom.id,
            'planning_run_id': run.id, 'planning_line_id': self.line.id,
            'planning_hourly_capacity': 80, 'date_start': fields.Datetime.now()})
        self.line.mo_id = self.mo

    def wizard(self, quantity=900, expected=980):
        return self.env['injection.plan.quantity.change'].with_user(self.manager).create({
            'line_id': self.line.id, 'quantity': quantity, 'expected_qty': expected, 'reason': '시험 수요 감축'})

    def test_direct_mo_line_and_standard_wizard_cannot_diverge(self):
        with self.assertRaises(UserError):
            self.mo.with_context(_planning_quantity_change=True).write({'product_qty': 900})
        with self.assertRaises(UserError):
            self.line.write({'planned_qty': 900})
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env['change.production.qty'].create({'mo_id': self.mo.id, 'product_qty': 900}).change_prod_qty()
        with self.assertRaises(UserError):
            self.line.unlink()
        self.assertEqual(self.mo.product_qty, self.line.planned_qty)

    def test_manager_reduction_keeps_plan_and_mo_together(self):
        self.wizard().action_apply()
        self.assertEqual(self.mo.product_qty, 900)
        self.assertEqual(self.line.planned_qty, 900)
        with self.assertRaises(UserError):
            self.wizard(800, expected=980).action_apply()

    def test_planner_cannot_confirm_and_increase_is_rejected(self):
        with self.assertRaises(AccessError):
            self.wizard().with_user(self.planner).action_apply()
        with self.assertRaises(UserError):
            self.wizard(1000).action_apply()

    def test_resin_basis_uses_bom_quantity_and_uom(self):
        basis = self.line._material_basis()[0]
        self.assertAlmostEqual(basis['unit_qty'], 0.5)
        self.assertAlmostEqual(self.line.planned_qty * basis['unit_qty'], 490)
        self.assertIn('490', self.line.calculation_detail)

    def test_calculation_snapshot_cannot_be_forged_or_rewritten(self):
        self.assertIn('스냅샷이 없습니다', self.line.calculation_detail)
        with self.assertRaises(UserError):
            self.line.write({'calculation_policy_snapshot':{'min_lot_size':1}})
        values = {'planning_run_id':self.line.planning_run_id.id,
            'plan_date':self.day, 'workcenter_id':self.line.workcenter_id.id,
            'mold_id':self.line.mold_id.id, 'product_id':self.inj.id, 'planned_qty':100}
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['injection.planning.line'].with_user(self.planner).with_context(
                default_calculation_policy_snapshot={'min_lot_size':1}).create(values)
        rows = [values]
        config = self.env['injection.planning.config']._get_active_shift_config()
        self.line.planning_run_id._add_calculation_policy_snapshot(rows, config)
        row = self.env['injection.planning.line'].create(rows)
        before = dict(row.calculation_policy_snapshot)
        self.assertIn('계산 당시 최소 로트', row.calculation_detail)
        config.write({'default_min_lot_size':config.default_min_lot_size + 100})
        self.assertEqual(row.calculation_policy_snapshot, before)
