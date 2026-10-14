"""[2026-10-04 사용자 결정] 조기 생산 한도(early_limit_days) — 교체 인식 방식.

공동 테스트(UAT run 5)에서 10일치 수요가 앞 닷새에 전부 배치돼 조기 생산이 총량의 83% 였고,
'재고를 고려한 일정 배치' 설정은 교체 인식 경로에 도달하지 않았다. 한도는 안전재고와 같은
'수요가 있는 날 N개' 기준이다.
"""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import tagged

from .test_setup_aware_sequencing import SetupAwareCase


@tagged("post_install", "-at_install")
class TestEarlyLimit(SetupAwareCase):
    """A 만 쓰는 사출기 1대, 하루 8h, 1개/시간. 수요 D0 2, D1 2, D2 2, D3 2 (한 날 8h 로 전부 당길 수 있음)."""

    def _four_days(self):
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=4)
        self._mount(self.mold_a)
        return self._demands([(self.fin, 0, 2.0), (self.fin, 1, 2.0), (self.fin, 2, 2.0), (self.fin, 3, 2.0)], 4)

    def _finish_dates(self, run):
        return sorted((str(l.plan_date), str(l.finish_date), l.planned_qty) for l in run.line_ids)

    def test_limit_zero_places_each_on_its_need_date(self):
        self.config.early_limit_days = 0
        run = self._four_days(); run.action_calculate_plan()
        rows = self._finish_dates(run)
        self.assertEqual(len(run.unassigned_ids), 0)
        for plan_date, finish, _q in rows:
            self.assertEqual(plan_date, finish, "한도 0: 필요일 당일에 끝나야 한다 %s" % (rows,))
        self.assertEqual(run.early_qty, 0.0)
        self.assertEqual(run.late_qty, 0.0)

    def test_limit_one_allows_one_demand_day_ahead_only(self):
        self.config.early_limit_days = 1
        run = self._four_days(); run.action_calculate_plan()
        self.assertEqual(len(run.unassigned_ids), 0)
        for plan_date, finish, _q in self._finish_dates(run):
            gap = (fields.Date.to_date(plan_date) - fields.Date.to_date(finish)).days
            self.assertLessEqual(gap, 1, "한도 1: 필요일보다 하루까지만 앞설 수 있다")
        self.assertEqual(run.late_qty, 0.0)

    def test_large_limit_keeps_consolidation(self):
        """한도가 충분히 크면 기존처럼 같은 금형으로 이어 붙여 교체 0·앞당김 허용."""
        self.config.early_limit_days = 10
        run = self._four_days(); run.action_calculate_plan()
        self.assertEqual(len(run.unassigned_ids), 0)
        self.assertEqual(run.late_qty, 0.0)
        self.assertGreater(run.early_qty, 0.0, "한도가 크면 앞당겨 묶는다")

    def test_due_date_beats_limit_and_is_recorded(self):
        """한도 0 인데 필요일 당일 가동시간(8h)보다 많은 물량(12개)이면 납기를 위해 한도를 넘겨 당기고 경고를 남긴다."""
        self.config.early_limit_days = 0
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=2)
        self._mount(self.mold_a)
        run = self._demands([(self.fin, 1, 12.0)], 2); run.action_calculate_plan()
        self.assertEqual(len(run.unassigned_ids), 0)
        self.assertEqual(run.late_qty, 0.0, "한도 때문에 납기를 놓치면 안 된다")
        body = " ".join(run.message_ids.mapped("body"))
        self.assertIn("조기 생산 한도", body)

    def test_negative_limit_rejected(self):
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.config.early_limit_days = -1
