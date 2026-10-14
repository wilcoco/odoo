"""R135 교체 인식 순서기 — 수용 기준·독립시험 요구에 맞춘 개발 자체 시험.

새 방식(`setup_aware`)만 켠다. 예상값은 제품 코드를 재사용하지 않고 시험 안의 단순 시뮬레이터/전수열거로 만든다.
휴리스틱이므로 '전역 최적' 을 단언하지 않는다 — 작은 문제에서 전수열거의 최선과 같은지만 본다.
"""
import itertools
from datetime import date, timedelta

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_pp03_pp06 import PlanningCase, TestPhysicalConstraintsPP06
from .test_pr_peer_review import TestCompanyIsolationPR08
from .test_pp07_pp08 import TestCrossPlanReservation, TestCreatedMoReconciliation
from .bom_fixture import injection_bom


class SetupAwareCase(PlanningCase):
    """고정물: 교체 인식 방식, 하루 8h 주간(필요 시 야간 4h), 교체 2h, 1개/시간."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 안전재고 0: 이 파일은 납기·교체·용량을 본다. 새 방식의 달력일 안전재고(3일)를 켜 두면 D3 수요가 D1 필요량으로
        # 당겨져(4+20=24개/12h) 예시 자체가 불가능해진다 — 4ef8c49 실행에서 그렇게 찍혔다. 안전재고는 별도 파일이 본다.
        cls.config.write({"sequencing_mode": "setup_aware", "default_changeover": 2.0, "safety_stock_days": 0})

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("SA-기", ton=1000.0)
        self.mold_a = self._mold("SA-A", ton=100.0)
        self.mold_a.changeover_hours = 2.0
        self.cap_a = self._cap(self.wc, self.mold_a, cycle=3600.0)
        self.prod_b = self.env["product.product"].create({"name": "SA-부품B", "default_code": "SA-B", "type": "consu", "is_storable": True})
        self.fin_b = self.env["product.product"].create({"name": "SA-완제품B", "default_code": "SA-FINB", "type": "consu"})
        injection_bom(self.env, {"product_tmpl_id": self.fin_b.product_tmpl_id.id, "product_qty": 1.0,
                                    "bom_line_ids": [(0, 0, {"product_id": self.prod_b.id, "product_qty": 1.0})]})
        self.mold_b = self._mold("SA-B", ton=100.0, product=self.prod_b)
        self.mold_b.changeover_hours = 2.0
        self.cap_b = self._cap(self.wc, self.mold_b, cycle=3600.0)

    def _demands(self, spec, days):
        """spec: [(완제품, 필요일 오프셋, 수량)] → run"""
        Demand = self.env["production.demand"]
        demands = Demand.browse()
        for fin, offset, qty in spec:
            demands |= Demand.create({"demand_date": self.day + timedelta(days=offset), "product_id": fin.id,
                                      "quantity": qty, "source": "manual"})
        run = self.env["injection.planning.run"].create({"plan_date_from": self.day, "plan_date_to": self.day + timedelta(days=days - 1)})
        run.demand_ids = [(6, 0, demands.ids)]
        return run

    def _mount(self, mold):
        self.env["injection.machine.availability"].create({
            "workcenter_id": self.wc.id, "date": self.day - timedelta(days=1),
            "day_shift_hours": 0.0, "night_shift_hours": 0.0, "last_mold_id": mold.id})

    def _by_date(self, run):
        return {(l.product_id.id, str(l.plan_date)): l for l in run.line_ids}


@tagged("post_install", "-at_install")
class TestDueDateBeatsChangeover(SetupAwareCase):

    def test_review7_example_legacy_late_new_on_time(self):
        """검토 #7 재구성. 12h/일(주 8 + 야 4), A: 4@D1 + 20@D3, B: 4@D2, 교체 2h, 현 금형 A.
        기존: A 그룹 연속(D1 12h, D2 12h) → B 는 D3 → 지연. 새 방식: D1 A 12개, D2 A 6 + 교체 + B 4, D3 교체 + A 6 → 지연 0, 교체 2."""
        self._availability(self.wc, day_h=8.0, night_h=4.0, days=3)
        self._mount(self.mold_a)
        spec = [(self.fin, 0, 4.0), (self.fin, 2, 20.0), (self.fin_b, 1, 4.0)]
        self.config.write({"sequencing_mode": "legacy"})
        legacy = self._demands(spec, 3); legacy.action_calculate_plan()
        legacy_late = legacy.line_ids.filtered(lambda l: l.product_id == self.prod_b and l.is_late)
        self.assertTrue(legacy_late, "전제: 기존 방식은 B 의 D2 납기를 놓쳐야 한다(연속 배치)")
        self.config.write({"sequencing_mode": "setup_aware"})
        run = self._demands(spec, 3); run.action_calculate_plan()
        late = run.violation_ids.filtered(lambda v: v.kind == "late")
        table = [(l.product_id.default_code, str(l.plan_date), str(l.start_time), str(l.end_time), l.mold_id.code,
                  l.changeover_needed, l.planned_qty, l.daily_sequence) for l in run.line_ids.sorted(lambda l: (l.start_time, l.id))]
        self.assertFalse(late, "새 방식에서 지연: %s\n배치 라인: %s\n미배정: %s\n안내: %s" % (
            late.mapped("detail"), table, run.unassigned_ids.mapped("detail"), run.sequencing_note))
        self.assertEqual(run.feasibility, "feasible")
        self.assertEqual(run.total_changeovers, 2, "A→B→A 두 번이어야 한다")
        self.assertIn("전역 최적", run.sequencing_note)

    def test_urgent_due_forces_a_changeover(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)
        self._mount(self.mold_a)
        run = self._demands([(self.fin_b, 0, 4.0), (self.fin, 2, 4.0)], 3); run.action_calculate_plan()
        first = run.line_ids.sorted("start_time")[0]
        self.assertEqual(first.mold_id, self.mold_b, "긴급 납기(B, D1)가 현 금형 유지보다 먼저여야 한다")
        self.assertTrue(first.changeover_needed)
        self.assertFalse(run.violation_ids.filtered(lambda v: v.kind == "late"))

    def test_r141_f2_same_due_tie_keeps_current_mold(self):
        """[R141 F2] A 장착, A2·B2 모두 D1, 8h → A 먼저(교체 1). ID/생성 순서를 뒤집어도 같다."""
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=1)
        self._mount(self.mold_a)
        for spec in ([(self.fin, 0, 2.0), (self.fin_b, 0, 2.0)], [(self.fin_b, 0, 2.0), (self.fin, 0, 2.0)]):
            run = self._demands(spec, 1); run.action_calculate_plan()
            order = [l.mold_id.code for l in run.line_ids.sorted("start_time")]
            self.assertEqual(order[0], self.mold_a.code, "동률 납기에서 현 금형이 아니라 교체를 먼저: %s" % order)
            self.assertEqual(run.total_changeovers, 1)
            self.assertEqual(run.feasibility, "feasible")

    def test_r141_f2_control_urgent_due_still_forces_changeover(self):
        """대조군: B 가 8h 안에 못 들어가는 긴급이면 현 금형 유지보다 납기가 앞선다."""
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=2)
        self._mount(self.mold_a)
        run = self._demands([(self.fin, 1, 2.0), (self.fin_b, 0, 6.0)], 2); run.action_calculate_plan()
        order = [l.mold_id.code for l in run.line_ids.sorted("start_time")]
        self.assertEqual(order[0], self.mold_b.code, "긴급 B(2+6=8h, D1)가 먼저여야 한다: %s" % order)
        self.assertFalse(run.violation_ids.filtered(lambda v: v.kind == "late"))

    def test_current_mold_is_kept_when_nothing_is_urgent(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=4)
        self._mount(self.mold_a)
        run = self._demands([(self.fin, 3, 4.0), (self.fin_b, 3, 4.0)], 4); run.action_calculate_plan()
        first = run.line_ids.sorted("start_time")[0]
        self.assertEqual(first.mold_id, self.mold_a, "긴급이 없으면 현 금형(A)을 유지해야 한다")
        self.assertEqual(run.total_changeovers, 1)


@tagged("post_install", "-at_install")
class TestCapacityIsHonest(SetupAwareCase):

    def test_eight_hours_plus_two_setup_does_not_fit_eight_hour_day(self):
        """8h 가동에 8h 생산 + 2h 교체 = 10h 를 정상 수용하면 오류다."""
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=1)
        self._mount(self.mold_b)                                  # A 로 교체 필요
        run = self._demands([(self.fin, 0, 8.0)], 1); run.action_calculate_plan()
        placed = sum(run.line_ids.mapped("planned_qty"))
        self.assertLess(placed, 8.0, "10h 작업이 8h 에 통째로 들어갔다")
        self.assertTrue(run.unassigned_ids, "넘친 수량이 미배정으로 남아야 한다")
        self.assertNotEqual(run.feasibility, "feasible")
        with self.assertRaises(UserError):
            run.action_confirm_generate_mo()

    def test_two_products_contending_for_one_machine_same_day(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=2)
        self._mount(self.mold_a)
        run = self._demands([(self.fin, 0, 6.0), (self.fin_b, 0, 6.0)], 2); run.action_calculate_plan()
        self.assertTrue(run.violation_ids.filtered(lambda v: v.severity == "hard"), "같은 날 6h+2h+6h 는 8h 에 못 들어간다")
        self.assertIn(run.feasibility, ("infeasible_proven", "infeasible_unresolved"))
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()

    def test_one_physical_mold_runs_on_one_machine(self):
        wc2 = self._workcenter("SA-기2", ton=1000.0)
        self._cap(wc2, self.mold_a, cycle=3600.0)
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=2)
        self._availability(wc2, day_h=8.0, night_h=0.0, days=2)
        run = self._demands([(self.fin, 0, 6.0), (self.fin, 1, 6.0)], 2); run.action_calculate_plan()
        machines = run.line_ids.filtered(lambda l: l.mold_id == self.mold_a).mapped("workcenter_id")
        self.assertEqual(len(machines), 1, "실물 금형 하나가 두 사출기에 동시에 잡혔다")


@tagged("post_install", "-at_install")
class TestAgainstExhaustiveEnumeration(SetupAwareCase):

    def _simulate(self, order, hours_per_day, setup, current):
        """독립 시뮬레이터(제품 코드 미사용): 작업을 순서대로 8h/일 창에 넣고 (지연수량, 교체수) 를 센다."""
        t, late, changeovers, cur = 0.0, 0.0, 0, current
        for mold, due_offset, qty in order:
            if mold != cur:
                t += setup; changeovers += 1; cur = mold
            t += qty
            finish_day = int((t - 1e-9) // hours_per_day)
            if finish_day > due_offset:
                late += qty
        return late, changeovers

    def test_r141_f3_four_job_toy_matches_the_exhaustive_optimum(self):
        """[R141 F3] A3@D1·B3@D1·A3@D2·B3@D3, A 장착, 8h·교체 2h → 전수열거 최선 = 지연 0·교체 2.
        이전 후보(55753e7)는 B 먼저 + A 를 6개로 연장해 late 5·교체 3 이었다(독립시험 83fa660)."""
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)
        self._mount(self.mold_a)
        jobs = [("A", 0, 3.0), ("B", 0, 3.0), ("A", 1, 3.0), ("B", 2, 3.0)]
        best = min(self._simulate(p, 8.0, 2.0, "A") for p in itertools.permutations(jobs))
        self.assertEqual(best, (0.0, 2), "오라클 전제")
        run = self._demands([(self.fin, 0, 3.0), (self.fin_b, 0, 3.0), (self.fin, 1, 3.0), (self.fin_b, 2, 3.0)], 3)
        run.action_calculate_plan()
        table = [(l.mold_id.code, str(l.plan_date), str(l.start_time), str(l.end_time), l.planned_qty, l.changeover_needed)
                 for l in run.line_ids.sorted(lambda l: (l.start_time, l.id))]
        self.assertEqual((run.late_qty, run.total_changeovers), best, "제품 %s ≠ 최선 %s · 라인 %s · 위반 %s" % (
            (run.late_qty, run.total_changeovers), best, table, run.violation_ids.mapped("detail")))
        self.assertEqual(run.feasibility, "feasible")
        # 원 수요일 보존: D2 수요분 라인은 plan_date D2 로 남아야 한다(첫 납기로 재분류 금지)
        self.assertTrue(run.line_ids.filtered(lambda l: l.product_id == self.inj and l.plan_date == self.day + timedelta(days=1)))

    def test_r141_f3_inventory_ceiling_blocks_advance_production(self):
        """재고 상한 대조군: 상한이 있으면 연장(선행 생산)이 상한을 넘기지 않는다."""
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)
        self._mount(self.mold_a)
        self.inj.max_inventory_qty = 3.0
        run = self._demands([(self.fin, 0, 3.0), (self.fin, 1, 3.0), (self.fin, 2, 3.0)], 3); run.action_calculate_plan()
        self.assertFalse(run.violation_ids.filtered(lambda v: v.kind == "max_inventory_excess"),
                         "상한을 넘긴 선행 생산: %s" % run.violation_ids.mapped("detail"))
        self.assertFalse(run.violation_ids.filtered(lambda v: v.kind == "late"))

    def test_heuristic_matches_the_best_of_all_orders_on_a_toy(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)
        self._mount(self.mold_a)
        jobs = [("A", 0, 4.0), ("B", 1, 4.0), ("A", 2, 4.0)]
        best = min(self._simulate(p, 8.0, 2.0, "A") for p in itertools.permutations(jobs))
        run = self._demands([(self.fin, 0, 4.0), (self.fin_b, 1, 4.0), (self.fin, 2, 4.0)], 3); run.action_calculate_plan()
        got = (run.late_qty, run.total_changeovers)
        self.assertEqual(got[0], best[0], "지연 수량이 전수열거 최선(%s)보다 나쁘다: %s" % (best, got))
        self.assertLessEqual(got[1], best[1] + 1, "교체 횟수가 전수열거 최선보다 2 이상 많다: %s vs %s" % (got, best))


@tagged("post_install", "-at_install")
class TestBoundariesAndDeterminism(SetupAwareCase):

    def test_night_window_across_midnight_counts_one_changeover_and_is_not_late(self):
        """20:00 시작 야간 8h 는 설비 달력이 자정에서 창을 둘로 나눈다(첫 실행 확인). 그래도 교체는 한 번,
        D 에 시작한 야간은 D 의 작업이라 지연이 아니며, 자정 뒤 라인은 D+1 의 1번이다."""
        self.config.write({"night_shift_start": 20.0, "night_shift_hours": 8.0, "day_shift_hours": 0.0})
        self._availability(self.wc, day_h=0.0, night_h=8.0, days=2)
        self._mount(self.mold_b)
        run = self._demands([(self.fin, 0, 5.0)], 2); run.action_calculate_plan()
        lines = run.line_ids.filtered(lambda l: l.product_id == self.inj).sorted("start_time")
        self.assertTrue(lines)
        self.assertEqual(sum(lines.mapped("changeover_count")), 1, "교체가 중복 계산됐다")
        self.assertEqual(sum(lines.mapped("changeover_in_span_hours")), 2.0)
        self.assertFalse(run.violation_ids.filtered(lambda v: v.kind == "late"),
                         "D 에 시작한 야간 작업이 자정을 넘었다고 지연으로 찍혔다: %s" % run.violation_ids.mapped("detail"))
        after_midnight = lines.filtered(lambda l: l.start_date > self.day)
        if after_midnight:
            self.assertEqual(after_midnight[0].daily_sequence, 1)

    def test_unconfirmed_zero_and_negative_changeover(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=1)
        self.mold_a.changeover_hours = 0.0                        # 저장 ≠ 확인
        self.assertFalse(self.mold_a.changeover_hours_confirmed)
        run = self._demands([(self.fin, 0, 2.0)], 1); run.action_calculate_plan()
        line = run.line_ids.filtered(lambda l: l.mold_id == self.mold_a)[:1]
        self.assertEqual(line.changeover_source, "mold_unconfirmed")
        self.mold_a.action_confirm_changeover_hours()
        self.assertTrue(self.mold_a.changeover_hours_confirmed)
        with self.assertRaises(Exception):
            self.mold_a.changeover_hours = -1.0

    def test_capability_override_zero_is_a_confirmed_zero(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=1)
        self._mount(self.mold_b)
        self.cap_a.write({"changeover_override": True, "changeover_hours": 0.0})
        run = self._demands([(self.fin, 0, 2.0)], 1); run.action_calculate_plan()
        line = run.line_ids.filtered(lambda l: l.mold_id == self.mold_a)[:1]
        self.assertEqual(line.changeover_source, "capability")
        self.assertEqual(line.changeover_hours, 0.0)
        self.assertTrue(line.changeover_needed, "교체는 필요하되 시간이 0 인 것이다")

    def test_repeat_is_deterministic(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)
        self._mount(self.mold_a)
        run = self._demands([(self.fin, 0, 4.0), (self.fin_b, 1, 4.0), (self.fin, 2, 4.0)], 3)
        run.action_calculate_plan()
        snap = lambda r: [(l.workcenter_id.id, str(l.start_time), l.planned_qty, l.mold_id.id, l.daily_sequence) for l in r.line_ids.sorted(lambda l: (l.start_time, l.id))]
        first = snap(run); run.action_reset_draft(); run.action_calculate_plan()
        self.assertEqual(snap(run), first)

    def test_r141_f1_safety_advance_is_policy_not_hard_late(self):
        """[R141 F1] 5일 매일 실수요 2, 하루 4h, 재고 0, 안전재고 3일(달력). 실수요는 전부 제때 → 하드 지연 0,
        안전재고 부족은 정책 위반으로만 기록되고 관리자 확인 뒤 확정 가능."""
        self.config.write({"safety_stock_days": 3})
        try:
            self._availability(self.wc, day_h=4.0, night_h=0.0, days=5)
            self._mount(self.mold_a)
            run = self._demands([(self.fin, k, 2.0) for k in range(5)], 5); run.action_calculate_plan()
            late = run.violation_ids.filtered(lambda v: v.kind == "late")
            self.assertFalse(late, "안전재고 선행량이 하드 지연으로 둔갑: %s · 라인 %s" % (
                late.mapped("detail"), [(str(l.plan_date), str(l.start_date), l.planned_qty) for l in run.line_ids.sorted("start_time")]))
            short = run.violation_ids.filtered(lambda v: v.kind == "safety_shortfall")
            self.assertTrue(short, "4h/일로 안전재고 6 을 못 채우므로 정책 부족이 기록돼야 한다")
            self.assertEqual(set(short.mapped("severity")), {"policy"})
            self.assertEqual(run.feasibility, "feasible")
            with self.assertRaises(UserError):
                run.action_confirm_generate_mo()               # 정책 위반은 관리자 확인 전 확정 불가
            run.action_acknowledge_violations()
            self.assertTrue(run.violations_acknowledged)
            # 선행분 라인은 덮는 실수요 날짜를 납기로 갖는다 — D1 납기로 재분류되지 않는다
            self.assertTrue(run.line_ids.filtered(lambda l: l.plan_date > self.day))
        finally:
            self.config.write({"safety_stock_days": 0})

    def test_safety_basis_is_demand_dates_in_both_modes(self):
        """[R144 사용자 확정] 안전재고 N일 = 원청 생산계획에 수요가 있는 날 N개. 달력일 아님."""
        self.assertEqual(self.config._safety_stock_basis(), "demand_dates")
        self.config.write({"sequencing_mode": "legacy"})
        try:
            self.assertEqual(self.config._safety_stock_basis(), "demand_dates")
        finally:
            self.config.write({"sequencing_mode": "setup_aware"})


# ── [검토 #8] 기존 회귀의 의미 있는 부분집합을 새 방식으로도 돌린다 — 결함을 숨기지 않기 위해
class _SetupAwareRegressionMixin:
    # Odoo 의 로더(`odoo/tests/loader.py get_module_test_cases`)는 클래스 자신의 __dict__ 에 정의된 test_ 만 모은다.
    # 상속만 한 부분집합 클래스는 이 표지가 없으면 시험 0건이다 — 02421c7·d2a73f0·0f00ce7 실행에서 실제로 한 번도 돌지 않았다.
    allow_inherited_tests_method = True

    @classmethod
    def setUpClass(cls):
        # 부모 고정물이 클래스 객체에 캐시한 레코드(`_cont_cal`)는 부모 시험이 끝난 커서의 것이라 상속하면
        # "Cursor already closed" 가 난다(24b85ba 전체 실행: 부분집합 4 클래스 26 error 전부). 여기서 새로 만든다.
        cls._cont_cal = None
        super().setUpClass()
        cls.config.write({"sequencing_mode": "setup_aware"})


@tagged("post_install", "-at_install")
class TestPhysicalConstraintsPP06SetupAware(_SetupAwareRegressionMixin, TestPhysicalConstraintsPP06):
    pass


@tagged("post_install", "-at_install")
class TestCompanyIsolationPR08SetupAware(_SetupAwareRegressionMixin, TestCompanyIsolationPR08):
    pass


@tagged("post_install", "-at_install")
class TestCrossPlanReservationSetupAware(_SetupAwareRegressionMixin, TestCrossPlanReservation):
    pass


@tagged("post_install", "-at_install")
class TestCreatedMoReconciliationSetupAware(_SetupAwareRegressionMixin, TestCreatedMoReconciliation):
    pass
