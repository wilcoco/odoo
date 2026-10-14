"""R135 §4.3~4.5 — 일별 순서 유도, 예상 양품 궤적, 위반 기록, 수동 수정 재검증, 반복 결정성.

이 파일은 기존(`legacy`) 방식 위에서 평가 계층만 본다. 새 순서 방식은 `test_setup_aware_sequencing.py` 가 본다.
"""
from datetime import timedelta

from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_pp03_pp06 import PlanningCase
from .bom_fixture import injection_bom


@tagged("post_install", "-at_install")
class TestDailySequenceAndTrajectory(PlanningCase):

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("R135-기", ton=1000.0)
        self.mold = self._mold("R135-금형", ton=100.0)
        self.cap = self._cap(self.wc, self.mold, cycle=3600.0)          # 1개/시간
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)

    def _plan(self, qty, days=1):
        run = self._run(qty=qty, days=days)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids, "계획 라인이 없다")
        return run

    def test_daily_sequence_numbers_lines_per_machine_and_work_day(self):
        run = self._plan(qty=6.0)
        lines = run.line_ids.sorted(lambda l: (l.workcenter_id.id, l.start_date, l.start_time))
        seen = {}
        for line in lines:
            key = (line.workcenter_id.id, line.start_date)
            seen[key] = seen.get(key, 0) + 1
            self.assertEqual(line.daily_sequence, seen[key], "일별 순서가 시작 시각 순 1,2,3… 이 아니다: %s" % line.display_name)
            self.assertTrue(line.due_end_time, "납기 상한이 비었다")
            self.assertEqual(run.env["injection.planning.config"]._get_active_shift_config()
                             .utc_to_shift_local(line.due_end_time).date(), line.plan_date,
                             "납기 상한이 필요일 업무 종료가 아니다")

    def test_expected_good_separates_total_from_good(self):
        self.cap.defect_rate = 10.0
        self.cap.initial_scrap = 2
        self.config.default_changeover = 0.0
        run = self._plan(qty=9.0)
        line = run.line_ids.sorted("start_time")[0]
        self.assertGreater(line.planned_qty, line.expected_good_qty, "총생산량이 예상 양품보다 커야 한다")
        expected = max(0.0, (line.planned_qty - line.initial_scrap) * 0.9)
        self.assertAlmostEqual(line.expected_good_qty, expected, places=6)
        summary = run.summary_ids.filtered(lambda s: s.plan_date == line.finish_date)
        self.assertTrue(summary)
        self.assertAlmostEqual(sum(summary.mapped("expected_good_qty")),
                               sum(run.line_ids.filtered(lambda l: l.finish_date == line.finish_date).mapped("expected_good_qty")), places=6)

    def test_late_line_is_recorded_as_violation_and_plan_is_infeasible(self):
        """8h 가동에 12개(12h) → 다음 날로 밀림 → 납기 지연 위반. (기간 1일이면 미배정이 되므로 2일)"""
        self.inj.max_inventory_qty = 12.0                    # legacy 풀 캐퍼(16)를 12 로 잘라 전제를 고정
        run = self._plan(qty=12.0, days=2)
        late = run.line_ids.filtered("is_late")
        self.assertTrue(late, "지연 라인이 없다 — 전제가 틀렸다")
        kinds = run.violation_ids.mapped("kind")
        self.assertIn("late", kinds)
        self.assertIn(run.feasibility, ("infeasible_proven", "infeasible_unresolved"))
        self.assertAlmostEqual(run.late_qty, sum(late.mapped("expected_good_qty")), places=6)
        self.assertIn("전역 최적 미보장", run.sequencing_note)

    def test_within_capacity_plan_is_feasible_with_no_violation(self):
        self.inj.max_inventory_qty = 4.0                     # legacy 풀 캐퍼 16 > 8h 창 → 미배정이 되므로 상한으로 고정
        run = self._plan(qty=4.0)
        self.assertFalse(run.violation_ids.filtered(lambda v: v.kind in ("late", "safety_shortfall")))
        self.assertEqual(run.feasibility, "feasible")

    def test_max_inventory_excess_is_recorded_not_silently_accepted(self):
        self.inj.max_inventory_qty = 3.0
        self.config.inventory_aware_scheduling = False
        run = self._plan(qty=2.0)
        # legacy 순수요는 풀 캐퍼(8개)까지 만들되 최대재고 3 으로 자른다 → 초과는 없어야 한다.
        excess = run.violation_ids.filtered(lambda v: v.kind == "max_inventory_excess")
        self.assertFalse(excess, "최대재고를 지킨 계획에 초과 위반이 찍혔다: %s" % excess.mapped("detail"))
        # 사람이 수량을 올리면 재검증이 초과를 잡아야 한다
        line = run.line_ids.sorted("start_time")[0]
        line.write({"planned_qty": line.planned_qty + 10.0})
        run.action_revalidate_sequence()
        self.assertTrue(run.violation_ids.filtered(lambda v: v.kind == "max_inventory_excess"),
                        "수량을 올렸는데 최대재고 초과가 기록되지 않았다")

    def test_manual_time_overlap_is_reported_by_revalidation(self):
        run = self._plan(qty=6.0, days=2)
        lines = run.line_ids.sorted("start_time")
        self.assertGreaterEqual(len(lines), 2, "겹침을 만들려면 라인이 둘 필요하다")
        first, second = lines[0], lines[1]
        second.write({"start_time": first.start_time, "end_time": first.end_time})   # 같은 사출기 시각 겹침
        run.action_revalidate_sequence()
        last = run.message_ids[0].body
        self.assertIn("겹침", str(last))

    def test_revalidation_is_refused_on_draft(self):
        run = self._run(qty=4.0)
        with self.assertRaises(UserError):
            run.action_revalidate_sequence()

    def test_repeated_calculation_is_deterministic(self):
        run = self._plan(qty=6.0, days=2)
        snapshot = lambda r: [(l.workcenter_id.id, str(l.start_time), str(l.end_time), l.planned_qty, l.daily_sequence,
                               l.changeover_source) for l in r.line_ids.sorted(lambda l: (l.start_time, l.id))]
        first = snapshot(run)
        run.action_reset_draft(); run.action_calculate_plan()
        self.assertEqual(snapshot(run), first, "같은 입력의 두 번째 계산이 다르다")

    def test_changeover_source_is_recorded(self):
        run = self._plan(qty=4.0)
        first = run.line_ids.sorted("start_time")[0]
        # 전날 장착 기록이 없다: 장착 미확인(별도 사실) + 값 출처는 금형 미확인 값
        self.assertTrue(first.mount_unknown)
        self.assertEqual(first.changeover_source, "mold_unconfirmed")
        self.assertTrue(first.changeover_needed)

    def test_manual_order_is_applied_by_replacing_times(self):
        """검토 #5: 순서를 고치면 시간이 그 순서로 다시 놓이고 교체가 다시 계산된다 — 순서가 무시되지 않는다."""
        prod_b = self.env["product.product"].create({"name": "R135-부품B", "default_code": "R135-B", "type": "consu", "is_storable": True})
        fin_b = self.env["product.product"].create({"name": "R135-완제품B", "default_code": "R135-FINB", "type": "consu"})
        injection_bom(self.env, {"product_tmpl_id": fin_b.product_tmpl_id.id, "product_qty": 1.0,
                                    "bom_line_ids": [(0, 0, {"product_id": prod_b.id, "product_qty": 1.0})]})
        mold_b = self._mold("R135-금형B", ton=100.0, product=prod_b)
        self._cap(self.wc, mold_b, cycle=3600.0)
        self.inj.max_inventory_qty = prod_b.max_inventory_qty = 2.0   # legacy 풀 캐퍼가 8h 를 독점하지 않게
        run = self._run(qty=2.0, days=1)
        run.demand_ids |= self.env["production.demand"].create({"demand_date": self.day, "product_id": fin_b.id, "quantity": 2.0, "source": "manual"})
        run.action_calculate_plan()
        lines = run.line_ids.sorted("start_time")
        self.assertEqual(len(lines), 2, "전제: 같은 사출기·같은 날 라인 2개")
        first_product = lines[0].product_id
        lines[0].daily_sequence, lines[1].daily_sequence = 2, 1          # 순서를 뒤집는다
        run.action_apply_manual_order()
        new_lines = run.line_ids.sorted("start_time")
        self.assertEqual(len(new_lines), 2)
        self.assertNotEqual(new_lines[0].product_id, first_product, "사용자 순서가 시간에 반영되지 않았다")
        self.assertEqual([l.daily_sequence for l in new_lines], [1, 2])
        self.assertTrue(new_lines[1].changeover_needed, "금형이 바뀌는 두 번째 라인의 교체가 다시 계산되지 않았다")
        self.assertFalse(run.derived_stale)
