"""Physical mold reservation must apply across all compatible machines."""
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_pp07_pp08 import MaterialCase


@tagged("post_install", "-at_install")
class TestSharedMoldReservation(MaterialCase):
    def setUp(self):
        super().setUp()
        self.config.write({"day_shift_hours": 8, "night_shift_hours": 0,
                           "day_shift_start": 8, "night_shift_start": 20})
        self.env["injection.machine.mold.capability"].search([
            ("workcenter_id", "=", self.wc.id), ("mold_id", "=", self.mold.id),
        ]).cycle_time = 288  # 100 pieces in one 8-hour shift
        self.other_wc = self._workcenter("SM-second-machine", ton=1200)
        self._cap(self.other_wc, self.mold, cycle=288)

    def _pair(self):
        first, second = self._calculated(days=2), self._calculated(days=2)
        self.assertEqual(len(first.line_ids), 1)
        self.assertEqual(len(second.line_ids), 1)
        first.line_ids.workcenter_id = self.wc
        second.line_ids.workcenter_id = self.other_wc
        first.action_revalidate_requirements()
        second.action_revalidate_requirements()
        self.assertEqual(first.line_ids.start_time, second.line_ids.start_time)
        self.assertEqual(first.line_ids.mold_id, second.line_ids.mold_id)
        return first, second

    def test_other_machine_cannot_confirm_the_same_physical_mold(self):
        first, second = self._pair()
        first.generate_manufacturing_orders()
        with self.assertRaises(UserError):
            second.generate_manufacturing_orders()
        self.assertFalse(second.mo_ids)
        self.assertFalse(second.line_ids.mo_id)

    def test_scheduler_uses_the_next_free_mold_window(self):
        first, second = self._pair()
        first.line_ids.write({"planned_qty": 25,
                              "end_time": first.line_ids.start_time + timedelta(hours=2)})
        first.action_revalidate_requirements()
        first.generate_manufacturing_orders()
        lines, unassigned = second._schedule(
            {(self.inj.id, str(self.day)): 100}, second._get_config())
        self.assertFalse(unassigned)
        self.assertEqual(sum(line["planned_qty"] for line in lines), 100)
        self.assertEqual(min(line["start_time"] for line in lines), first.line_ids.end_time)
        for line in lines:
            self.assertFalse(line["start_time"] < first.line_ids.end_time
                             and first.line_ids.start_time < line["end_time"])

    def test_cancelled_mold_reservation_can_be_used_again(self):
        first, second = self._pair()
        first.generate_manufacturing_orders()
        first.mo_ids.action_cancel()
        second.generate_manufacturing_orders()
        self.assertEqual(len(second.mo_ids), 1)
        self.assertEqual(first.mo_ids.state, "cancel")

    def test_distinct_physical_molds_may_run_on_distinct_machines(self):
        first, second = self._pair()
        other_mold = self._mold("SM-independent-mold", ton=100)
        self._cap(self.other_wc, other_mold, cycle=288)
        second.line_ids.mold_id = other_mold
        second.action_revalidate_requirements()
        first.generate_manufacturing_orders()
        second.generate_manufacturing_orders()
        self.assertEqual(len(first.mo_ids | second.mo_ids), 2)

    def test_same_plan_cannot_double_book_a_mold_on_two_machines(self):
        first, second = self._pair()
        second.line_ids.planning_run_id = first
        first.action_revalidate_requirements()
        with self.assertRaises(UserError):
            first.generate_manufacturing_orders()
        self.assertFalse(first.mo_ids)
        self.assertFalse(first.line_ids.mo_id)
