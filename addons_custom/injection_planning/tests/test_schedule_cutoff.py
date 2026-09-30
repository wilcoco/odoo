"""Explicit remaining-time constraint for same-day recalculation."""
from datetime import datetime, time, timedelta
from odoo.exceptions import UserError
from odoo.tests.common import tagged
from .test_pp03_pp06 import PlanningCase


@tagged('post_install', '-at_install')
class TestScheduleCutoff(PlanningCase):
    def setUp(self):
        super().setUp()
        self.config.write({'day_shift_start': 8, 'day_shift_hours': 8, 'night_shift_hours': 0,
                           'inventory_aware_scheduling': True, 'safety_stock_days': 0})
        self.wc = self._workcenter('CUTOFF', ton=1000)
        self.mold = self._mold('CUTOFF-M', ton=100)
        self.mold.changeover_hours = .5
        self._cap(self.wc, self.mold, cycle=60)
        self._availability(self.wc, 8, 0, days=2)
        self.inj.max_inventory_qty = 1
        self.cutoff = self.config.shift_local_to_utc(datetime.combine(self.day, time(12)))

    def test_setup_and_production_start_after_cutoff(self):
        control = self._run(qty=1)
        control.action_calculate_plan()
        self.assertLess(control.line_ids[0].occupancy_start_time or control.line_ids[0].start_time, self.cutoff)
        run = self._run(qty=1)
        run.schedule_not_before = self.cutoff
        run.action_calculate_plan()
        self.assertTrue(run.line_ids)
        self.assertTrue(all((r.occupancy_start_time or r.start_time) >= self.cutoff for r in run.line_ids))
        self.assertTrue(all(r.start_time >= self.cutoff for r in run.line_ids))

    def test_exhausted_today_is_not_invented_as_capacity(self):
        run = self._run(qty=1, days=2)
        run.schedule_not_before = self.cutoff + timedelta(hours=5)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids or run.unassigned_ids)
        self.assertTrue(all(r.start_time >= run.schedule_not_before for r in run.line_ids))
        self.assertTrue(run.unassigned_ids or any(run.line_ids.mapped('is_late')))

    def test_reviewed_cutoff_cannot_be_changed(self):
        run = self._run(qty=1)
        run.schedule_not_before = self.cutoff
        run.action_calculate_plan()
        with self.assertRaises(UserError):
            run.schedule_not_before = False

    def test_manual_line_cannot_cross_cutoff_at_generation(self):
        run = self._run(qty=1)
        run.schedule_not_before = self.cutoff
        run.action_calculate_plan()
        row = run.line_ids[0]
        row.write({'occupancy_start_time': self.cutoff - timedelta(minutes=1)})
        with self.assertRaises(UserError):
            run._validate_planning_line(row)
