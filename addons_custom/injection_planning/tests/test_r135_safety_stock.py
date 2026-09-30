"""R135 안전재고 — 사용자 확정: 기본 3일, 설정에서 변경. 달력일 기준은 교체 인식 방식(아스트라 명시 가정).

`_safety_stock_target` 하나를 순수요·요약·평가가 같이 쓴다. 여기서는 그 함수와 스냅샷·확정 차단·권한을 본다.
"""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import tagged

from .test_pp03_pp06 import PlanningCase

Run = "injection.planning.run"


@tagged("post_install", "-at_install")
class TestSafetyStockTarget(PlanningCase):

    def test_default_is_three_days(self):
        fresh = self.env["injection.planning.config"].new({})
        self.assertEqual(fresh.safety_stock_days, 3)

    def test_days_must_be_a_whole_number(self):
        with self.assertRaises(ValidationError):
            self.config.write({"safety_stock_days": 2.5})
        with self.assertRaises(ValidationError):
            self.config.write({"safety_stock_days": -1})
        self.config.write({"safety_stock_days": 5})
        self.assertEqual(self.config.safety_stock_days, 5)

    def test_calendar_days_include_days_without_demand(self):
        """D=1일, 수요 3일 10·6일 20. N=3(달력) → 2·3·4일 = 10. 기존(수요 날짜 3개) → 3·6일 = 30."""
        demand = {"2026-10-03": 10.0, "2026-10-06": 20.0}
        target_cal, ok = self.env[Run]._safety_stock_target(demand, "2026-10-01", 3, "calendar_days", "2026-10-06")
        self.assertEqual((target_cal, ok), (10.0, True))
        target_legacy, _ = self.env[Run]._safety_stock_target(demand, "2026-10-01", 3, "demand_dates", "2026-10-06")
        self.assertEqual(target_legacy, 30.0)

    def test_three_to_five_days_raises_the_target(self):
        demand = {"2026-10-02": 5.0, "2026-10-04": 5.0, "2026-10-06": 5.0}
        three, _ = self.env[Run]._safety_stock_target(demand, "2026-10-01", 3, "calendar_days", "2026-10-06")
        five, _ = self.env[Run]._safety_stock_target(demand, "2026-10-01", 5, "calendar_days", "2026-10-06")
        self.assertEqual((three, five), (10.0, 15.0))

    def test_end_of_horizon_is_flagged_not_zeroed(self):
        demand = {"2026-10-02": 5.0}
        target, complete = self.env[Run]._safety_stock_target(demand, "2026-10-01", 3, "calendar_days", "2026-10-02")
        self.assertEqual(target, 5.0)
        self.assertFalse(complete, "수집 범위 밖을 0 수요로 단정하면 안 된다 — 범위 부족 표시가 필요하다")


@tagged("post_install", "-at_install")
class TestSafetyStockSnapshotAndGate(PlanningCase):

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("SS-기", ton=1000.0)
        self.mold = self._mold("SS-금형", ton=100.0)
        self._cap(self.wc, self.mold, cycle=3600.0)
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)

    def test_plan_snapshots_applied_days_and_basis(self):
        self.config.write({"safety_stock_days": 3})
        run = self._run(qty=4.0); run.action_calculate_plan()
        self.assertEqual(run.safety_stock_days_applied, 3)
        self.assertEqual(run.safety_stock_basis_applied, "demand_dates")   # 고정물은 legacy
        self.assertFalse(run.settings_changed)

    def test_changing_the_setting_marks_the_draft_and_blocks_confirmation(self):
        run = self._run(qty=4.0); run.action_calculate_plan()
        self.config.write({"safety_stock_days": 5})
        run.invalidate_recordset()
        self.assertTrue(run.settings_changed)
        with self.assertRaises(UserError) as caught:
            run.action_confirm_generate_mo()
        self.assertIn("재계산", str(caught.exception))
        # 초안 재계산이 새 값을 적용한다
        run.action_reset_draft(); run.action_calculate_plan()
        self.assertEqual(run.safety_stock_days_applied, 5)
        self.assertFalse(run.settings_changed)

    def test_confirmed_plan_keeps_its_snapshot_after_setting_change(self):
        run = self._run(qty=4.0); run.action_calculate_plan()
        applied, lines_before = run.safety_stock_days_applied, [(l.planned_qty, str(l.start_time)) for l in run.line_ids]
        self.config.write({"safety_stock_days": 5})
        run.invalidate_recordset()
        self.assertEqual(run.safety_stock_days_applied, applied, "설정 변경이 확정 전 스냅샷을 덮어썼다")
        self.assertEqual([(l.planned_qty, str(l.start_time)) for l in run.line_ids], lines_before)

    def test_planning_user_cannot_change_the_setting(self):
        user = self.env["res.users"].create({
            "name": "SS-담당", "login": "ss_planner", "email": "ss_planner@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id, self.env.ref("injection_planning.group_planning_user").id])]})
        with self.assertRaises(AccessError):
            self.config.with_user(user).write({"safety_stock_days": 5})

    def test_r144_config_basis_skips_days_without_demand(self):
        """[R144 사용자 확정] 설정의 기준은 '수요가 있는 날 N개'. 금요일 D, 주말 수요 없음 → 월·화·수 3일치."""
        self.assertEqual(self.config._safety_stock_basis(), "demand_dates")
        demand = {"2026-10-09": 7.0, "2026-10-12": 10.0, "2026-10-13": 20.0, "2026-10-14": 30.0, "2026-10-15": 40.0}
        target, complete = self.env[Run]._safety_stock_target(
            demand, "2026-10-09", 3, self.config._safety_stock_basis(), "2026-10-15")
        self.assertEqual((target, complete), (60.0, True))
