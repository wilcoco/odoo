"""제3자 검토(2026-09-10) P1-PP04·PP05 회귀 — 가용재고의 날짜, 필요일과 실제 일정일.

두 결함은 같은 뿌리다. 계획이 '언제' 를 잃어버리고 수량만 본다.
- PP04: 10일 뒤 완료 예정인 MO 를 오늘 쓸 수 있는 재고로 센다.
- PP05: 가동시간이 모자라 다음 날로 밀려도 필요일에 들어온 것처럼 집계한다.
"""
from datetime import date, timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged

from .test_pp03_pp06 import PlanningCase
from .bom_fixture import injection_bom


@tagged("post_install", "-at_install")
class TestAvailabilityIsDatedPP04(PlanningCase):
    """UAT-PP04 — 필요한 날짜의 가용재고만 쓴다."""

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("PP4-기", ton=1000.0)
        self._cap(self.wc, self._mold("PP4-금형", ton=100.0))

    def _open_mo(self, qty, finish_date):
        """아직 만들어지지 않은(확정 상태) MO 하나.

        완료 예정일은 확정 **뒤에** 못박는다 — `action_confirm` 이 리드타임으로
        `date_finished` 를 다시 계산해 덮어쓰기 때문이다.
        """
        mo = self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": qty,
            "date_start": fields.Datetime.to_datetime(
                "%s 01:00:00" % (finish_date - timedelta(days=1))),
        })
        mo.action_confirm()
        self.assertEqual(mo.state, "confirmed")
        mo.date_finished = fields.Datetime.to_datetime("%s 01:00:00" % finish_date)
        self.assertEqual(mo.date_finished.date(), finish_date,
                         "고정하려는 완료 예정일이 다시 계산돼 덮였다")
        return mo

    def test_pp04_future_mo_is_not_todays_stock(self):
        """현재고 0, 오늘 100 필요, 10일 뒤 완료 예정 MO 100 → **오늘 생산이 필요하다**.

        예전에는 미래 MO 잔량을 날짜 없이 초기 재고에 전량 더해 "생산 불필요" 가 됐다.
        """
        self._open_mo(100.0, self.day + timedelta(days=10))
        run = self._run(qty=100.0, days=1)
        net = run._calculate_net_requirements({(self.inj.id, str(self.day)): 100.0})
        self.assertTrue(net, "미래 완료 MO 를 오늘 가용재고로 세어 생산을 건너뛰었다")
        self.assertGreaterEqual(sum(net.values()), 100.0)

    def test_pp04_mo_finishing_by_the_need_date_is_counted(self):
        """필요일까지 완료되는 MO 는 그대로 가용재고다(과생산 방지).

        (계획 시작일보다 **앞선** 예정일은 '지연' 이라 따로 다룬다 — 아래 시험 참조.)
        """
        self._open_mo(100.0, self.day)
        run = self._run(qty=100.0, days=2)
        net = run._calculate_net_requirements({(self.inj.id, str(self.day)): 100.0})
        self.assertFalse(net, "필요일에 들어올 물량인데 또 생산 계획을 세웠다")

    def test_pp04_receipt_lands_on_its_own_date(self):
        """이틀치 수요 중 둘째 날 도착분은 둘째 날부터 쓸 수 있다."""
        second = self.day + timedelta(days=1)
        self._open_mo(100.0, second)
        run = self._run(qty=100.0, days=2)
        receipts = run._scheduled_receipts([self.inj.id])
        self.assertEqual(dict(receipts[self.inj.id]), {second: 100.0})

    def test_pp04_overdue_mo_is_not_usable_stock(self):
        """예정일이 지난 미완료 MO 는 **입고로 세지 않는다**.

        계획 시작일에 확실히 들어온다고 단정하면 결품을 다시 가린다. 수량은 '지연
        예정량' 으로 따로 보여 주고, 실행 가능 재고로 쓰려면 사람이 재예정해야 한다.
        (아스트라 2026-09-10 18:56)
        """
        self._open_mo(100.0, self.day - timedelta(days=30))
        run = self._run(qty=100.0, days=2)
        receipts, overdue = run._open_mo_receipts([self.inj.id])
        self.assertFalse(receipts.get(self.inj.id),
                         "지연 MO 를 확실한 입고로 세었다")
        self.assertAlmostEqual(overdue[self.inj.id], 100.0)

    def test_pp04_overdue_mo_does_not_suppress_production(self):
        """지연 MO 가 있어도 오늘 필요한 수량은 계획된다."""
        self._open_mo(100.0, self.day - timedelta(days=30))
        run = self._run(qty=100.0, days=2)
        issues = []
        net = run.with_context(plan_issues=issues)._calculate_net_requirements(
            {(self.inj.id, str(self.day)): 100.0})
        self.assertTrue(net, "지연 예정량을 가용재고로 세어 생산을 건너뛰었다")
        self.assertTrue(any("지연 예정량" in i for i in issues),
                        "지연 예정량 사실이 어디에도 남지 않았다")

    def test_pp04_other_company_mo_is_not_our_stock(self):
        other = self.env["res.company"].create({"name": "PP4-회사B"})
        mo = self.env["mrp.production"].with_company(other).create({
            "product_id": self.inj.id, "product_qty": 100.0, "company_id": other.id})
        mo.action_confirm()
        run = self._run(qty=100.0, days=1)
        receipts = run._scheduled_receipts([self.inj.id])
        self.assertFalse(receipts.get(self.inj.id),
                         "다른 회사의 진행 물량을 우리 가용재고로 셌다")

    def test_pp04_chart_and_calculation_share_the_same_series(self):
        """차트의 초기재고도 계산과 같은 시계열을 쓴다.

        예전에는 계산이 진행 MO 를 전량 더하고 차트는 qty_available 만 써서 어긋났다.
        """
        second = self.day + timedelta(days=1)
        self._open_mo(100.0, second)
        run = self._run(qty=100.0, days=2)
        run.action_calculate_plan()
        rows = {str(s.plan_date): s for s in run.summary_ids
                if s.product_id == self.inj}
        self.assertIn(str(self.day), rows)
        self.assertIn(str(second), rows)
        # 첫날 시작 재고에는 둘째 날 입고가 들어 있으면 안 된다
        first_row = rows[str(self.day)]
        self.assertLess(first_row.stock_start, 100.0,
                        "둘째 날 도착분이 첫날 시작 재고에 들어갔다")


@tagged("post_install", "-at_install")
class TestNeedDateVsScheduleDatePP05(PlanningCase):
    """UAT-PP05 — 필요일과 실제 일정일을 분리하고, 늦으면 늦다고 말한다."""

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("PP5-기")
        self._cap(self.wc, self._mold("PP5-금형"), cycle=360.0)   # 시간당 10개
        self._availability(self.wc, day_h=8.0, night_h=0.0, days=3)

    def _calculated(self, qty=100.0, days=3):
        run = self._run(qty=qty, days=days)
        run.action_calculate_plan()
        return run

    def test_pp05_line_carries_both_dates(self):
        """라인은 필요일과 실제 시작·완료일을 따로 들고 있다."""
        run = self._calculated()
        self.assertTrue(run.line_ids)
        for line in run.line_ids:
            self.assertTrue(line.start_date)
            self.assertTrue(line.finish_date)
            self.assertGreaterEqual(line.finish_date, line.start_date)
        # 하루 8h 가동에 10h 작업 → 반드시 다음 날로 넘어간다
        self.assertTrue(run.line_ids.filtered("is_late"))
        late = run.line_ids.filtered("is_late")[0]
        self.assertGreater(late.finish_date, late.plan_date)

    def test_pp05_production_is_charted_on_the_finish_date(self):
        """차트의 생산량은 **완료일**에 찍힌다 — 필요일에 들어온 척하지 않는다."""
        run = self._calculated()
        by_date = {}
        for s in run.summary_ids.filtered(lambda r: r.product_id == self.inj):
            by_date[str(s.plan_date)] = s
        line_by_finish = {}
        for line in run.line_ids:
            line_by_finish.setdefault(str(line.finish_date), 0.0)
            line_by_finish[str(line.finish_date)] += line.planned_qty
        for date_str, qty in line_by_finish.items():
            self.assertIn(date_str, by_date)
            self.assertAlmostEqual(by_date[date_str].planned_qty, qty, places=2,
                                   msg="생산량이 완료일이 아닌 날짜에 집계됐다")
        # 밀린 날에도 생산이 잡혀 있어야 한다(필요일에 몰려 있으면 결품이 숨는다)
        self.assertGreater(len(line_by_finish), 1,
                           "10시간 작업이 하루에 다 들어간 것으로 집계됐다")

    def test_pp05_shortage_on_the_need_date_is_visible(self):
        """필요일의 종료 재고가 음수로 남아야 결품이 보인다."""
        run = self._calculated()
        need_row = run.summary_ids.filtered(
            lambda r: r.product_id == self.inj and str(r.plan_date) == str(self.day))
        self.assertTrue(need_row)
        self.assertLess(need_row.stock_end, 0.0,
                        "늦게 끝나는데 필요일 재고가 채워진 것처럼 나온다")

    def test_pp05_material_is_consumed_on_the_start_date(self):
        """원재료는 필요일이 아니라 작업이 실제 시작되는 날 소비된다."""
        resin = self.env["product.product"].create(
            {"name": "PP5-수지", "is_storable": True})
        injection_bom(self.env, {
            "product_tmpl_id": self.inj.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": resin.id, "product_qty": 1.0})]})
        run = self._calculated()
        start_dates = set(run.line_ids.mapped("start_date"))
        daily_dates = set(run.material_daily_ids.filtered(
            lambda d: d.material_id == resin).mapped("plan_date"))
        self.assertTrue(daily_dates)
        self.assertTrue(daily_dates <= start_dates,
                        "원재료 소요가 실제 작업 시작일이 아닌 날짜에 잡혔다")
