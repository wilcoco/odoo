"""최종 배치가 **미래 필요분을 첫날로 당겨** 재고 상한을 넘기는가.

[아스트라 2026-09-12 08:09] 「같은 원자료 `assignments` 는 필요일 Sep24 의 11/7개
외에 **Sep25~28 용 물량도 전부 `start_date=finish_date=Sep24`** 입니다. 예: qty2
need Sep25 / start Sep24 / finish Sep24, qty3 need Sep26 / start Sep24 / finish Sep24.
**순수요 수량의 상한 적용과 최종 일정의 선행 배치는 다른 단계**입니다.
`_take_hours`(1265 이하)의 **앞 윈도부터 배정** 경로를 함께 보십시오.」

제가 앞서 「미설정 0 무제한이 원인」이라고 회신했는데 **틀렸습니다.** 예행은
`max` 8/5 를 실제로 설정했고(`configured_max 8/5`), 그런데도 `stock_end 24/15` 가
나왔습니다. 상한은 **순수요 단계에서 지켜지고**, 그 뒤 **배치 단계가 미래분을 앞
윈도로 당깁니다.**

이 시험은 그 숫자 모양을 그대로 재현한다 — 상한 8, 첫날 수요 3, 이후 8·8·8.
  - 당기면: 첫날 생산 27 → 첫날 종료재고 **24** (상한 8 의 3 배)
  - 필요일을 지키면: 첫날은 수요 3 + 상한 버퍼까지만
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .test_pp03_pp06 import PlanningCase
from .bom_fixture import injection_bom

MAX_INVENTORY = 8.0
DAY0_DEMAND = 3.0
LATER_DEMAND = 8.0


@tagged("post_install", "-at_install")
class TestEarlyPlacement(PlanningCase):
    """UAT — 미래 필요분의 선행 배치가 재고 상한을 넘기지 않는다."""

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("EP-기", ton=1000.0)
        self.cap = self._cap(self.wc, self._mold("EP-금형", ton=100.0), cycle=1.0)
        # 첫날 하루에 전량을 넣을 수 있는 능력을 준다 — 그래야 「당길 수 있는데도
        # 당기지 않는가」를 본다. 능력이 모자라면 시험이 아무것도 증명하지 못한다.
        self._availability(self.wc, day_h=12.0, night_h=12.0, days=4)
        self.inj.max_inventory_qty = MAX_INVENTORY
        # **재고를 고려한 배치**를 켠다. 기본값(끔)은 기존 동작 그대로이고,
        # 그 보존은 `test_the_legacy_mode_is_unchanged` 가 따로 본다.
        self.config.inventory_aware_scheduling = True

    def _spread_run(self):
        """첫날 3, 이후 8·8·8 — 예행과 같은 모양."""
        Demand = self.env["production.demand"]
        demands = Demand.browse()
        for offset, qty in enumerate(
                (DAY0_DEMAND, LATER_DEMAND, LATER_DEMAND, LATER_DEMAND)):
            demands |= Demand.create({
                "demand_date": self.day + timedelta(days=offset),
                "product_id": self.fin.id, "quantity": qty, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=3)})
        run.demand_ids = [(6, 0, demands.ids)]
        run.action_calculate_plan()
        return run

    def test_future_demand_is_not_all_pulled_into_the_first_day(self):
        """**최종 배치 결과**에서 첫날 종료재고가 설정 상한을 넘지 않는다."""
        run = self._spread_run()
        self.assertTrue(run.line_ids, "계획 라인이 만들어지지 않았다")

        first = self.day
        # 완료일 기준 첫날 생산 (summary 와 같은 기준)
        produced_first = sum(
            line.planned_qty for line in run.line_ids
            if (line.finish_date or line.plan_date) == first)
        stock_end_first = produced_first - DAY0_DEMAND

        # 참고용으로 실제 배치를 남긴다 (실패 시 로그에서 바로 보이도록)
        placed = sorted(
            (str(line.plan_date), str(line.finish_date), line.planned_qty)
            for line in run.line_ids)
        self.assertLessEqual(
            stock_end_first, MAX_INVENTORY + 1e-6,
            "첫날 종료재고 %.0f 가 설정 상한 %.0f 을 넘었다 — 미래 필요분이 "
            "첫날로 당겨졌다. 배치: %s" % (stock_end_first, MAX_INVENTORY, placed))

    def test_no_line_finishes_before_its_need_date(self):
        """필요일보다 **앞서 끝나는** 라인이 있으면 그만큼 재고로 쌓인다."""
        run = self._spread_run()
        early = [(str(line.plan_date), str(line.finish_date), line.planned_qty)
                 for line in run.line_ids
                 if line.finish_date and line.plan_date
                 and line.finish_date < line.plan_date]
        self.assertFalse(
            early,
            "필요일보다 먼저 끝나는 라인이 있다(선행 배치): %s" % early)


    def test_the_legacy_mode_is_unchanged(self):
        """설정을 끄면 **종전 동작 그대로**다 — 기존 모드를 바꾸지 않았다."""
        self.config.inventory_aware_scheduling = False
        run = self._spread_run()
        pulled = [(str(line.plan_date), str(line.finish_date), line.planned_qty)
                  for line in run.line_ids
                  if line.finish_date and line.plan_date
                  and line.finish_date < line.plan_date]
        self.assertTrue(
            pulled,
            "설정을 껐는데 선행 배치가 사라졌다 — 기존 모드가 바뀌었다")

    def test_early_production_for_a_due_date_is_recorded(self):
        """필요일 이후 가동시간이 모자라면 당기되 **사유를 남긴다.**

        [아스트라 20260912 08:09] 「납기를 위해 조기생산이 불가피하면 **초과량·
        일자·사유를 명시**하는 반례도 필요합니다.」
        """
        self.config.inventory_aware_scheduling = True
        # **시간이 실제로 모자라게** 만든다. 기본 설정(cycle 1초 = 시간당 3600개)은
        # 20개를 몇 초에 만들어 어떤 가동시간으로도 부족해지지 않는다
        # (처음에 그렇게 짰다가 시험이 알려 줬다). 1시간에 1개로 늦춘다.
        self.cap.cycle_time = 3600.0
        # 마지막 날에만 가동시간을 조금만 준다 → 그날 필요분 20개(=20시간)는
        # 2시간 안에 못 만들므로 앞 구간으로 당겨야 한다.
        Avail = self.env["injection.machine.availability"]
        last = self.day + timedelta(days=3)
        Avail.search([("workcenter_id", "=", self.wc.id),
                      ("date", "=", last)]).write(
            {"day_shift_hours": 2.0, "night_shift_hours": 0.0})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": last})
        Demand = self.env["production.demand"]
        demands = Demand.browse()
        # 마지막 날 수요는 **상한 버퍼(8)로 못 덮을 만큼** 크게 준다. 작게 주면
        # 앞날 버퍼가 이미 덮어 그날 작업 자체가 생기지 않아 반례가 성립하지 않는다
        # (처음에 8 로 줬다가 시험이 그것을 알려 줬다).
        for offset, qty in enumerate(
                (DAY0_DEMAND, LATER_DEMAND, LATER_DEMAND, 20.0)):
            demands |= Demand.create({
                "demand_date": self.day + timedelta(days=offset),
                "product_id": self.fin.id, "quantity": qty, "source": "manual"})
        run.demand_ids = [(6, 0, demands.ids)]
        run.action_calculate_plan()
        # `action_calculate_plan` 은 자기 `plan_issues` 를 새로 묶으므로 밖에서
        # 리스트를 넘겨 볼 수 없다. 경고는 **chatter 에 게시**되므로 거기서 본다.
        posted = "\n".join(run.message_ids.mapped("body"))
        self.assertIn("조기 생산", posted,
                      "납기를 위해 당겼는데 사유가 남지 않았다: %s" % posted[:400])
        self.assertIn(str(last), posted, "당긴 일자가 사유에 없다")


    def test_a_midweek_due_date_is_met_by_pulling_forward(self):
        """[아스트라 20260912 08:25] 「중간 필요일 당일에는 2시간밖에 없고 작업은
        8시간인데 **다음날 이후** 가용시간이 충분하면 '조기생산 불필요'로 판단하여
        **need_date 다음날에 생산을 끝낼 수** 있습니다. **마지막날 부족 반례만으로는
        이를 못 잡습니다.** 필요일이 주중간이고 **전날 선행생산 가능/당일 부족/
        다음날 충분**한 반례에서 납기를 지키는 선행생산 또는 명확한 불가 판정을
        검증하십시오.」

        지적대로였습니다. 앞 판의 `_free_hours(since=필요일)` 은 **계획기간 끝까지**
        셌으므로 이 상황을 「충분」으로 보고 필요일을 넘겨 끝냈습니다.
        """
        self.config.inventory_aware_scheduling = True
        self.cap.cycle_time = 3600.0          # 1시간에 1개
        Avail = self.env["injection.machine.availability"]
        need_day = self.day + timedelta(days=1)
        # 전날 충분 / 당일 2시간만 / 다음날 충분
        Avail.search([("workcenter_id", "=", self.wc.id),
                      ("date", "=", need_day)]).write(
            {"day_shift_hours": 2.0, "night_shift_hours": 0.0})

        Demand = self.env["production.demand"]
        demand = Demand.create({
            "demand_date": need_day, "product_id": self.fin.id,
            "quantity": 8.0, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=3)})
        run.demand_ids = [(6, 0, demand.ids)]
        run.action_calculate_plan()

        lines = run.line_ids.filtered(lambda l: l.plan_date == need_day)
        self.assertTrue(lines, "필요일 작업이 계획되지 않았다")
        # **납기를 지킨다** — 필요일을 넘겨 끝나면 안 된다
        late = [(str(l.plan_date), str(l.finish_date), l.planned_qty)
                for l in lines if l.finish_date and l.finish_date > need_day]
        posted = "\n".join(run.message_ids.mapped("body"))
        self.assertFalse(
            late,
            "필요일 %s 인데 그 뒤에 끝났다: %s / 경고: %s"
            % (need_day, late, posted[:300]))
        # 앞당겨 만들었다면 **사유가 남는다**
        self.assertIn("조기 생산", posted,
                      "당겨 만들었는데 사유가 남지 않았다: %s" % posted[:400])

    def test_windows_passed_over_for_a_later_need_date_stay_usable(self):
        """이름에 skip 을 쓰지 않는다 — 로그의 skip 집계와 헷갈린다(실제로 내
        집계가 이 이름을 skip 으로 셌다).

        [아스트라 20260912 08:25] 「`not_before` 로 건너뛴 윈도를 `machine_pos`
        증가로 **소비한 것처럼 잃지 않는지** 확인해 주십시오.」

        뒤에 처리되는 작업이 **더 이른 필요일**을 가지면 그 앞 구간을 써야 한다.
        """
        self.config.inventory_aware_scheduling = True
        self.cap.cycle_time = 3600.0
        Demand = self.env["production.demand"]
        # 늦은 필요일 수요를 먼저 만들고, 이른 필요일 수요를 나중에 만든다
        later = Demand.create({
            "demand_date": self.day + timedelta(days=2),
            "product_id": self.fin.id, "quantity": 5.0, "source": "manual"})
        earlier = Demand.create({
            "demand_date": self.day,
            "product_id": self.fin.id, "quantity": 5.0, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=3)})
        run.demand_ids = [(6, 0, (later | earlier).ids)]
        run.action_calculate_plan()

        first_day = run.line_ids.filtered(lambda l: l.plan_date == self.day)
        self.assertTrue(
            first_day,
            "첫날 필요분이 배치되지 않았다 — 건너뛴 윈도를 잃었을 수 있다. "
            "라인: %s" % [(str(l.plan_date), str(l.finish_date), l.planned_qty)
                          for l in run.line_ids])
        late = [l for l in first_day if l.finish_date and l.finish_date > self.day]
        self.assertFalse(
            late, "첫날 필요분이 첫날을 넘겨 끝났다 — 앞 구간을 잃었다")


@tagged("post_install", "-at_install")
class TestInventoryCeiling(PlanningCase):
    """약속한 확인 — **상한이 실제로 깎는가**, 그리고 **당일 결품이 상한을 이기는가**.

    앞 회신(`5741b20`)에서 「슬롯 반환 뒤 이 두 확인을 시험으로 넣겠습니다」라고
    적었습니다. 그 약속분입니다.
    """

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("IC-기", ton=1000.0)
        self.cap = self._cap(self.wc, self._mold("IC-금형", ton=100.0), cycle=1.0)
        self._availability(self.wc, day_h=12.0, night_h=12.0, days=2)

    def _net(self, demand_qty):
        run = self._run(qty=demand_qty, days=1)
        return run._calculate_net_requirements(
            {(self.inj.id, str(self.day)): float(demand_qty)})

    def test_the_ceiling_actually_trims_production(self):
        """상한을 설정하면 **하루 능력만큼**이 아니라 상한까지만 만든다."""
        self.inj.max_inventory_qty = 8.0
        net = self._net(3.0)
        produced = sum(net.values())
        # 하루 능력(시간당 3600 × 24h)은 훨씬 크다 — 상한이 깎아야 한다
        self.assertLess(produced, 1000.0,
                        "상한이 하루 능력을 깎지 못했다: %.0f" % produced)
        # 오늘 쓸 3 + 상한 8 = 11 (종료재고가 상한 8 이 된다)
        self.assertAlmostEqual(produced, 11.0, places=6,
                               msg="상한 적용 결과가 3+8 이 아니다")

    def test_no_ceiling_means_a_full_days_capacity(self):
        """상한 **미설정(0)** 이면 하루 능력만큼 만든다 — 회사 기본값 그대로다."""
        self.inj.max_inventory_qty = 0.0
        net = self._net(3.0)
        produced = sum(net.values())
        self.assertGreater(
            produced, 1000.0,
            "상한 미설정인데 생산이 하루 능력에 못 미친다: %.0f" % produced)

    def test_todays_shortage_is_never_starved_by_the_ceiling(self):
        """**당일 결품이 상한보다 우선**한다 — 상한 지키려고 오늘을 굶기지 않는다."""
        self.inj.max_inventory_qty = 1.0        # 아주 낮은 상한
        net = self._net(10.0)                   # 오늘 10 이 필요하다
        produced = sum(net.values())
        self.assertGreaterEqual(
            produced, 10.0,
            "상한 때문에 오늘 필요량을 못 채웠다: %.0f" % produced)
        # 구조상 상한이 오늘 결품을 굶길 수 없다:
        #   max_produce = max_inv - after_consume = 상한 + 부족분 ≥ 부족분
        self.assertLessEqual(
            produced, 11.0 + 1e-6,
            "상한 위로도 더 만들었다: %.0f" % produced)


@tagged("post_install", "-at_install")
class TestEarlyPlacementBoundaries(PlanningCase):
    """[아스트라 c8a262261b2] 「**Asia/Seoul 시간축 혼용**과 **교체시간을 조기
    제품수량으로 세는** 두 건 … UTC 로 바꾼 경계를 local naive 윈도와 비교하지 않기,
    실제 생산 segments 에서 **교체시간 차감 후** 조기 수량 집계, **KST 오후/자정
    교체 경계 반례**를 포함하십시오.」

    두 건 다 제 코드 결함이었습니다.
      ① 가동 구간(`_windows`)은 **교대 기준 현지 naive** 인데 경계를
         `shift_local_to_utc` 로 만들어 비교했습니다 — **9시간 어긋납니다.**
      ② 조기 수량을 배치 구간 전체로 세어 **교체시간까지 제품 수량**으로 봤습니다.
    """

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("EB-기", ton=1000.0)
        self.mold = self._mold("EB-금형", ton=100.0)
        self.cap = self._cap(self.wc, self.mold, cycle=3600.0)   # 1시간에 1개
        self.config.inventory_aware_scheduling = True
        # [아스트라 09:01] 「KST 시험에는 config 의 **실제 Asia/Seoul 설정을
        # 명시/단언**하십시오.」
        #
        # 단언만 넣어 보니 이 DB 의 교대 표준시는 **UTC** 였습니다(회사 달력·파트너
        # tz 미설정 → 기본값). KST 반례가 UTC 에서 돌면 아무것도 증명하지 못하므로
        # **명시로 설정한 뒤 단언**합니다. 교대 표준시는 회사 작업달력 → 파트너 tz
        # 순으로 정해집니다(`get_shift_timezone`).
        company = self.env.company
        if company.resource_calendar_id:
            company.resource_calendar_id.tz = "Asia/Seoul"
        else:
            company.partner_id.tz = "Asia/Seoul"
        self._continuous_calendar().tz = "Asia/Seoul"
        self.timezone = self.config.get_shift_timezone()
        self.assertEqual(self.timezone, "Asia/Seoul",
                         "KST 반례인데 교대 표준시가 %s 다" % self.timezone)

    def _plan_with(self, per_day, days=3, avail=None, last_mold=None):
        Demand = self.env["production.demand"]
        demands = Demand.browse()
        for offset, qty in enumerate(per_day):
            if not qty:
                continue
            demands |= Demand.create({
                "demand_date": self.day + timedelta(days=offset),
                "product_id": self.fin.id, "quantity": float(qty),
                "source": "manual"})
        Avail = self.env["injection.machine.availability"]
        for offset in range(days):
            hours = (avail or {}).get(offset, (12.0, 12.0))
            day = self.day + timedelta(days=offset)
            # 같은 시험에서 시나리오를 **두 번 돌릴 수 있다**(교체시간 차분 비교).
            # 가동시간은 (사출기, 날짜) 유일이므로 있으면 고쳐 쓴다.
            existing = Avail.search([("workcenter_id", "=", self.wc.id),
                                     ("date", "=", day)], limit=1)
            values = {"day_shift_hours": hours[0],
                      "night_shift_hours": hours[1]}
            if existing:
                existing.write(values)
            else:
                Avail.create(dict(values, workcenter_id=self.wc.id, date=day))
        if last_mold is not None:
            # 현재 장착 금형은 **계획 시작 전날**의 가동일정에서 읽는다
            # (`planning_run.py:1017-1022`). 계획 첫날에 걸면 읽히지 않는다 —
            # 처음에 그렇게 걸었다가 교체가 0h 로 계산됐다.
            prev = self.day - timedelta(days=1)
            record = Avail.search([("workcenter_id", "=", self.wc.id),
                                   ("date", "=", prev)], limit=1)
            if record:
                record.last_mold_id = last_mold.id
            else:
                Avail.create({"workcenter_id": self.wc.id, "date": prev,
                              "day_shift_hours": 0.0, "night_shift_hours": 0.0,
                              "last_mold_id": last_mold.id})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=days - 1)})
        run.demand_ids = [(6, 0, demands.ids)]
        run.action_calculate_plan()
        return run

    def test_the_need_date_boundary_uses_the_shift_local_axis(self):
        """경계가 **현지 naive** 축이어야 한다.

        UTC 로 만든 경계(KST-9h)와 비교하면 **전날 15:00 이후** 구간이 「필요일
        이후」로 잘못 보여, 필요일 **전날 오후**에 생산이 들어간다.
        """
        self.inj.max_inventory_qty = 8.0
        run = self._plan_with([0, 8, 0])          # 둘째 날에만 8 필요
        need_day = self.day + timedelta(days=1)
        lines = run.line_ids.filtered(lambda l: l.plan_date == need_day)
        self.assertTrue(lines, "필요일 작업이 계획되지 않았다")
        config = run._get_config()
        for line in lines:
            # 저장값은 UTC 다 — 현지로 되돌려 **필요일 당일**인지 본다
            local_start = config.utc_to_shift_local(line.start_time)
            self.assertGreaterEqual(
                local_start.date(), need_day,
                "필요일 %s 인데 현지 기준 %s 에 시작했다 — 시간축이 섞였다"
                % (need_day, local_start))

    def _early_report(self, changeover):
        """같은 시나리오를 **교체시간만 바꿔** 돌리고 조기 생산 보고를 읽는다."""
        self.mold.changeover_hours = changeover
        self.config.default_changeover = changeover
        self.inj.max_inventory_qty = 8.0
        run = self._plan_with([0, 4, 0],
                              avail={0: (12.0, 12.0), 1: (1.0, 0.0),
                                     2: (12.0, 12.0)})
        posted = "\n".join(run.message_ids.mapped("body"))
        import re as _re
        hours = _re.search(r"생산 ([0-9.]+)h", posted)
        pieces = _re.search(r"약 ([0-9]+)개", posted)
        return posted, (float(hours.group(1)) if hours else None,
                        int(pieces.group(1)) if pieces else None)

    def test_changeover_hours_are_not_counted_as_early_product(self):
        """조기 수량은 **교체시간을 뺀 생산 구간**에서만 센다.

        [아스트라 09:01] 「**발생을 assert** 하고 **예상 제품수량을 정확히 비교**
        하십시오. **전체 생산시간 이하만으로는 교체 차감 오류가 잡히지 않는 경우가
        있습니다.**」

        절대 개수를 제가 손으로 예측했더니 틀렸습니다(3 으로 적었는데 실제 12).
        순수요가 상한까지 버퍼를 쌓기 때문입니다. 그래서 **같은 시나리오를 교체시간
        0h / 2h 로만 바꿔 돌려 비교**합니다. 교체는 제품을 만들지 않으므로
        **조기 제품 수량은 같아야** 합니다. 교체를 제품으로 세면 2h 쪽이 커집니다.
        """
        posted0, (hours0, qty0) = self._early_report(0.0)
        self.assertIn("조기 생산", posted0,
                      "교체 0h 에서 조기 생산이 발생해야 한다: %s" % posted0[:300])
        posted2, (hours2, qty2) = self._early_report(2.0)
        self.assertIn("조기 생산", posted2,
                      "교체 2h 에서 조기 생산이 발생해야 한다: %s" % posted2[:300])
        self.assertIn("교체시간 제외", posted2)

        # **핵심**: 교체시간이 늘어도 **앞당겨 만든 제품 수는 같다**
        self.assertEqual(
            qty2, qty0,
            "교체시간 2h 를 넣었더니 조기 제품 수가 %s → %s 로 변했다 — "
            "교체시간을 제품으로 세고 있다" % (qty0, qty2))
        # 시간·수량이 서로 맞는지도 본다 (시간당 1개 구성)
        self.assertAlmostEqual(
            qty2, hours2 * self.cap.hourly_capacity, delta=1.0,
            msg="조기 수량이 생산 시간과 맞지 않는다 (%.2fh / %s개)" % (hours2, qty2))

    def test_changeover_before_the_need_date_makes_no_early_product(self):
        """[아스트라 09:14] 「전날 `(2h,0h)`, 필요일 `(12h,0h)`, 교체2h, 시간당1개,
        실제 계산 물량 12개(수요4+상한8) … 필요일 가용 12h < 총 14h 이므로 앞당기고
        **전날 2h 는 모두 교체로 소진**, 필요일 12h 에 제품 12개가 만들어져
        **조기제품 0** 이어야 합니다. … **실제 순수요가 12인지 먼저 단언**하고,
        교체 전날/양품생산 당일의 수량과 UTC→KST 시간을 확인하십시오.」

        앞서 제가 낸 차분 비교(0h/2h)는 **이 반례를 대신하지 못한다**는 지적을
        받아들입니다. 여기서 **실제 0개**를 검증합니다.
        """
        self.mold.changeover_hours = 2.0
        self.config.default_changeover = 2.0
        self.inj.max_inventory_qty = 8.0
        need_day = self.day + timedelta(days=1)

        # **교체가 실제로 필요해야** 한다. 첫 작업이면 금형 교체가 없으므로
        # (`needs_changeover`), 사출기에 **다른 금형이 물려 있는** 상태로 둔다
        # (`availability.last_mold_id`). 처음엔 이걸 안 걸어서 교체 0h 로 계산돼
        # 전날 창을 쓰지 않았다 — 시험이 그것을 알려 줬다.
        other_mold = self._mold("EB-이전금형", ton=100.0)
        run = self._plan_with([0, 4, 0],
                              avail={0: (2.0, 0.0),      # 전날 = 교체 2h 만
                                     1: (12.0, 0.0),     # 필요일 = 생산 12h
                                     2: (0.0, 0.0)},
                              last_mold=other_mold)
        config = run._get_config()

        # ① **순수요가 12 인지 먼저 단언한다** (수요 4 + 상한 8)
        net = run._calculate_net_requirements(
            {(self.inj.id, str(need_day)): 4.0})
        self.assertAlmostEqual(
            sum(net.values()), 12.0, places=6,
            msg="순수요가 12 가 아니다(수요4+상한8): %s" % net)

        # ② 계획 물량도 12
        self.assertAlmostEqual(
            sum(run.line_ids.mapped("planned_qty")), 12.0, places=6,
            msg="계획 물량이 12 가 아니다: %s"
                % [(str(l.plan_date), l.planned_qty) for l in run.line_ids])

        # ③ **조기 제품 0** — 교체가 전날에 걸려도 제품은 앞당기지 않았다
        posted = "\n".join(run.message_ids.mapped("body"))
        self.assertNotIn(
            "조기 생산", posted,
            "전날은 교체만 했는데 조기 생산으로 적혔다: %s" % posted[:400])

        # ④ 제품 생산은 **필요일**에 끝난다 — UTC 저장값을 KST 로 되돌려 본다
        starts = sorted(config.utc_to_shift_local(line.start_time)
                        for line in run.line_ids if line.start_time)
        finishes = sorted(line.finish_date for line in run.line_ids
                          if line.finish_date)
        self.assertTrue(starts and finishes, "배치 시각이 없다")
        self.assertEqual(
            finishes[-1], need_day,
            "제품 생산이 필요일에 끝나지 않았다: %s" % finishes[-1])

        # ⑤ 교체가 실제로 적용됐다
        changeover_lines = run.line_ids.filtered("changeover_needed")
        self.assertTrue(changeover_lines,
                        "교체가 필요한 상태가 아니다 — 반례가 성립하지 않는다")
        self.assertAlmostEqual(
            sum(changeover_lines.mapped("changeover_hours")), 2.0, places=6,
            msg="교체 2h 가 적용되지 않았다")

        # ⑥ **제품 생산은 필요일에 시작**한다 — 전날 창은 교체가 가져갔다.
        #
        # 처음에는 「첫 라인이 전날에 시작해야 한다」고 단언했다가 틀렸습니다.
        # **교체만 있는 구간은 라인을 만들지 않습니다**(`seg_qty <= 0` 이면 건너뜀).
        # 그래서 전날 2h 교체 구간은 `line_ids` 에 나타나지 않고, 첫 **생산** 라인이
        # 필요일에서 시작합니다 — 지적하신 「전날 교체만·필요일 생산」 그대로입니다.
        self.assertEqual(
            starts[0].date(), need_day,
            "제품 생산이 필요일에 시작하지 않았다: %s" % starts[0])

        # ⑦ 전날 창이 교체로 소진됐음을 **수치로** 확인한다.
        #    필요일 가용 12h = 생산 12h 이므로 교체 2h 는 필요일에 들어갈 자리가
        #    없었고, 총 14h 중 나머지 2h 는 전날 창에서 쓰인 것이다.
        need_day_production_hours = sum(
            line.planned_qty / (self.cap.hourly_capacity or 1.0)
            for line in run.line_ids
            if (line.finish_date or line.plan_date) == need_day)
        self.assertAlmostEqual(
            need_day_production_hours, 12.0, places=6,
            msg="필요일 생산이 12h 가 아니다: %.2f" % need_day_production_hours)

    def test_changeover_length_does_not_change_the_early_product_count(self):
        """추가 회귀 — 교체시간을 늘려도 **조기 제품 수는 늘지 않는다.**

        [아스트라 09:14] 「0h/2h 교체 차분 비교는 **추가 회귀로 유용**하지만 … 기존
        요청 충족으로 판정할 수 없습니다.」 — 그래서 위 반례를 따로 두고, 이것은
        보조 회귀로만 남깁니다.
        """
        _p0, (_h0, qty0) = self._early_report(0.0)
        _p4, (_h4, qty4) = self._early_report(4.0)
        self.assertIsNotNone(qty0, "교체 0h 에서 조기 생산 보고가 없다")
        self.assertIsNotNone(qty4, "교체 4h 에서 조기 생산 보고가 없다")
        self.assertLessEqual(
            qty4, qty0,
            "교체시간을 0h→4h 로 늘렸더니 조기 제품이 %s → %s 로 늘었다"
            % (qty0, qty4))


@tagged("post_install", "-at_install")
class TestInventoryAwareSettingIsVisible(PlanningCase):
    """[아스트라 20260912-01 #3] 「`inventory_aware_scheduling` 은 **모델 필드만
    있고 config view 검색에 없었다.** 사용자가 이 모드를 켜고 수정할 수 있도록 실제
    사출계획 설정 화면의 적절한 그룹에 필드와 설명을 넣고 **권한별 view load** 를
    확인한다. **기본값 False 는 보존**한다.」
    """

    def test_the_setting_is_on_the_planning_config_screen(self):
        view = self.env.ref("injection_planning.view_injection_planning_config_form",
                            raise_if_not_found=False)
        if not view:
            candidates = self.env["ir.ui.view"].search(
                [("model", "=", "injection.planning.config"),
                 ("type", "=", "form")], limit=1)
            view = candidates[:1]
        self.assertTrue(view, "사출계획 설정 폼 화면이 없다")
        arch = self.env["injection.planning.config"].get_view(view.id, "form")
        self.assertIn("inventory_aware_scheduling", arch["arch"],
                      "설정 화면에 이 모드 필드가 없다 — 사용자가 켤 수 없다")

    def test_the_default_stays_off(self):
        """기본값 **False** 보존 — 켜는 것은 사용자의 선택이다."""
        fresh = self.env["injection.planning.config"].default_get(
            ["inventory_aware_scheduling"])
        self.assertFalse(
            fresh.get("inventory_aware_scheduling"),
            "기본값이 켜져 있다 — 기존 동작이 조용히 바뀐다")

    def test_a_planning_user_can_load_the_settings_screen(self):
        """권한별 화면 로드 — 계획 담당자가 열 수 있어야 한다."""
        planner = self.env["res.users"].create({
            "name": "IA-계획담당", "login": "ia_planner",
            "email": "ia_planner@example.com",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("injection_planning.group_planning_user").id,
                self.env.ref("mrp.group_mrp_user").id,
                self.env.ref("stock.group_stock_user").id,
            ])]})
        view = self.env["ir.ui.view"].search(
            [("model", "=", "injection.planning.config"),
             ("type", "=", "form")], limit=1)
        self.assertTrue(view, "설정 폼 화면이 없다")
        arch = self.env["injection.planning.config"].with_user(planner).get_view(
            view.id, "form")
        self.assertTrue(arch.get("arch"), "계획 담당자가 설정 화면을 열지 못했다")


@tagged("post_install", "-at_install")
class TestChangeoverSpanPersistence(PlanningCase):
    """[아스트라 20260912-01 #2] 「**이 계산이 맞다는 것과 저장된 계획/MO 의 자원
    예약이 맞다는 것은 별개**다. … 계획을 저장한 다음 **다른 계획이 전날 교체구간의
    같은 설비·금형을 예약하려 할 때 중복을 막는지** 검증한다. 같은 계산 함수 안의
    일시적 `machine_windows` 소진만으로 통과라고 하지 않는다.」
    """

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("CS-기", ton=1000.0)
        self.mold = self._mold("CS-금형", ton=100.0)
        self.cap = self._cap(self.wc, self.mold, cycle=3600.0)   # 1시간에 1개
        self.config.inventory_aware_scheduling = True
        self.inj.max_inventory_qty = 8.0
        self.mold.changeover_hours = 2.0
        self.config.default_changeover = 2.0
        Avail = self.env["injection.machine.availability"]
        # 전날 교체 2h / 필요일 생산 12h — 지정 구성 그대로
        for offset, hours in ((0, (2.0, 0.0)), (1, (12.0, 0.0))):
            Avail.create({"workcenter_id": self.wc.id,
                          "date": self.day + timedelta(days=offset),
                          "day_shift_hours": hours[0],
                          "night_shift_hours": hours[1]})
        self.other_mold = self._mold("CS-이전금형", ton=100.0)
        self.other_mold.changeover_hours = 0.0
        Avail.create({"workcenter_id": self.wc.id,
                      "date": self.day - timedelta(days=1),
                      "day_shift_hours": 0.0, "night_shift_hours": 0.0,
                      "last_mold_id": self.other_mold.id})

    def _calculated(self):
        demand = self.env["production.demand"].create({
            "demand_date": self.day + timedelta(days=1),
            "product_id": self.fin.id, "quantity": 4.0, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=1)})
        run.demand_ids = [(6, 0, demand.ids)]
        run.action_calculate_plan()
        return run

    def test_generated_mos_match_the_plan_without_re_adding_changeover(self):
        """확정·MO 생성에서 **라인마다** 시작/종료/수량이 계획과 맞는다.

        [아스트라 09:37] 「MO 는 plan line 의 `mo_id` 로 **직접 짝지어** 수량·시작·
        종료를 **각각** 비교하십시오. 현재 product/date 검색 후 max종료/min시작 한쪽
        부등식은 **중간행의 시각 불일치·시간 축소를 놓칩니다.**」

        맞습니다. 앞 판은 마지막/첫 값만 봐서 중간 행이 어긋나도 통과했습니다.
        """
        run = self._calculated()
        self.assertTrue(run.line_ids, "계획 라인이 없다")
        created = run.generate_manufacturing_orders()
        self.assertTrue(created, "제조오더가 생성되지 않았다")
        run.line_ids.invalidate_recordset()

        mapping = [(l.id, str(l.plan_date), l.planned_qty, str(l.start_time),
                    str(l.end_time), l.changeover_hours,
                    l.mo_id.id, l.mo_id.product_qty,
                    str(l.mo_id.date_start), str(l.mo_id.date_finished))
                   for l in run.line_ids]
        self.line_mo_mapping = mapping
        linked = run.line_ids.filtered("mo_id")
        self.assertEqual(
            len(linked), len(run.line_ids),
            "MO 와 연결되지 않은 계획 라인이 있다: %s"
            % [(str(l.plan_date), l.planned_qty) for l in run.line_ids
               if not l.mo_id])

        for line in linked:
            mo = line.mo_id
            # **수량**
            self.assertAlmostEqual(
                mo.product_qty, line.planned_qty, places=6,
                msg="라인 %s 수량이 MO 와 다르다: 계획 %s / MO %s"
                    % (line.id, line.planned_qty, mo.product_qty))
            # **시작** — 기존 `_validate_created_mo` 와 같은 1초 기준
            self.assertLessEqual(
                abs((mo.date_start - line.start_time).total_seconds()), 1,
                "라인 %s 시작이 MO 와 다르다: 계획 %s / MO %s"
                % (line.id, line.start_time, mo.date_start))
            # **종료** — 교체시간 재가산·시간 축소를 여기서 잡는다
            self.assertLessEqual(
                abs((mo.date_finished - line.end_time).total_seconds()), 1,
                "라인 %s 종료가 MO 와 다르다(교체 재가산/시간 축소 의심): "
                "계획 %s / MO %s\n전체 매핑(line,date,qty,start,end,co,mo,"
                "mo_qty,mo_start,mo_end): %s"
                % (line.id, line.end_time, mo.date_finished, mapping))

    def _second_plan_without_changeover(self):
        """전날 2h 에 **교체 없이** 2개를 만들 수 있는 두 번째 작업.

        [아스트라 09:37] 「현재 같은 금형 co2h/가용2h 이면 **예약이 없어도 교체만으로
        2h 가 소진되어** booked 빈값이 통과합니다. … 이전 장착 금형 `other` 와 별도
        품목/해당 cap 를 두 번째 작업에 사용해 **교체 0 으로 2개 배정 가능**하게
        하고, 첫 계획 확정 후에는 동일 설비 교체구간 겹침 때문에 **그 배정을
        거부**해야 합니다.」
        """
        # 전날 장착된 그 금형(`self.other_mold`)을 쓰므로 교체가 0 이다.
        second_product = self.env["product.product"].create({
            "name": "CS-둘째품", "default_code": "CS-P2", "type": "consu",
            "is_storable": True})
        second_fin = self.env["product.product"].create({
            "name": "CS-둘째완제품", "default_code": "CS-F2", "type": "consu"})
        injection_bom(self.env, {
            "product_tmpl_id": second_fin.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": second_product.id,
                                     "product_qty": 1.0})]})
        self.other_mold.product_id = second_product.id
        self.env["injection.machine.mold.capability"].create({
            "workcenter_id": self.wc.id, "mold_id": self.other_mold.id,
            "cycle_time": 3600.0, "defect_rate": 0.0, "initial_scrap": 0})
        demand = self.env["production.demand"].create({
            "demand_date": self.day, "product_id": second_fin.id,
            "quantity": 2.0, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day, "plan_date_to": self.day})
        run.demand_ids = [(6, 0, demand.ids)]
        run.action_calculate_plan()
        return run

    def test_the_control_second_plan_schedules_when_nothing_reserved(self):
        """**대조군** — 첫 계획이 없으면 두 번째 작업은 전날 2h 에 정상 배정된다.

        이것이 통과해야 아래 거부 시험이 「예약 때문」임을 말할 수 있다.
        """
        control = self._second_plan_without_changeover()
        self.assertTrue(
            control.line_ids,
            "대조군이 배정되지 않았다 — 거부 시험이 예약을 증명하지 못한다. "
            "미배정 사유: %s" % control.unassigned_ids.mapped("reason"))
        self.assertAlmostEqual(
            sum(control.line_ids.mapped("planned_qty")), 2.0, places=6,
            msg="대조군 수량이 2 가 아니다")
        self.assertAlmostEqual(
            sum(control.line_ids.mapped("changeover_hours")), 0.0, places=6,
            msg="대조군에 교체시간이 붙었다 — 능력 부족으로 통과할 위험이 있다")

    def test_two_precalculated_plans_cannot_both_confirm_the_changeover_window(self):
        """[아스트라 20260912 10:06] 「서로 다른 계획 A/B 를 **둘 다 미리 계산 →
        A 확정 → B 확정** 경로에서는 **계산 단계 보호를 지나쳐** 교체창 겹침이 남을
        수 있습니다. 공유 설비·금형 잠금 뒤의 **확정 재검증도 동일 점유 구간**을
        사용하고, 두 계획 선계산 후 순차 확정 반례를 추가하십시오.」

        맞습니다 — 저는 **계산 시점만** 고치고 확정 시점을 빼먹었습니다.
        여기서는 **둘 다 먼저 계산해 두고** A 를 확정한 뒤 B 를 확정합니다.
        B 는 A 의 **교체 점유 구간**과 겹치므로 거부돼야 합니다.
        """
        # A: 전날 교체 2h + 필요일 생산 (교체 점유가 전날 창을 가져간다)
        plan_a = self._calculated()
        # B: 같은 설비, 전날 2h 에 교체 없이 2개 — **A 확정 전에 미리 계산**한다
        plan_b = self._second_plan_without_changeover()
        self.assertTrue(
            plan_b.line_ids,
            "B 가 계산 단계에서 배정되지 않았다 — 순차 확정 반례가 성립하지 않는다")

        # A 를 먼저 확정한다
        plan_a.generate_manufacturing_orders()

        # 그 뒤 B 확정 — **A 의 교체 점유와 겹치므로 거부**돼야 한다
        with self.assertRaises(UserError) as caught:
            plan_b.generate_manufacturing_orders()
        message = str(caught.exception)
        self.assertTrue(
            "확정 계획이 있습니다" in message or "사용하는 확정 계획" in message
            or "겹치" in message,
            "거부 사유가 예약 충돌이 아니다: %s" % message[:400])

    def test_a_second_plan_cannot_rebook_the_changeover_window(self):
        """**저장된 계획 뒤** 다른 계획이 전날 교체 구간을 다시 예약하지 못한다.

        대조군(위)이 정상 배정되는 것과 짝으로 본다 — 거부가 **예약 때문**이지
        교체 능력 부족 때문이 아니어야 한다.
        """
        run = self._calculated()
        run.generate_manufacturing_orders()

        second = self._second_plan_without_changeover()
        booked = [(str(l.plan_date), str(l.start_time), str(l.end_time),
                   l.planned_qty, l.changeover_hours) for l in second.line_ids]
        self.assertFalse(
            booked,
            "첫 계획이 쓴 전날 교체 구간을 두 번째 계획이 다시 예약했다 — 이중 예약. "
            "배정: %s / 미배정: %s"
            % (booked, second.unassigned_ids.mapped("reason")))


@tagged("post_install", "-at_install")
class TestPlanDurationSourceIsGuarded(PlanningCase):
    """[아스트라 10:01] 소요 원천의 **범위와 보호**.

    1) MO 실제 수량으로 계산하는가(부모 12개 → 단위 1개가 12개분을 물려받지 않는가)
    2) 아무 계획행/타 회사·품목 행을 붙일 수 있는가
    3) 달력 원천이 없으면 지어내지 않는가
    """

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("DS-기", ton=1000.0)
        self.mold = self._mold("DS-금형", ton=100.0)
        self.cap = self._cap(self.wc, self.mold, cycle=3600.0)   # 1시간에 1개
        self._availability(self.wc, day_h=12.0, night_h=12.0, days=2)

    def _line(self):
        run = self._run(qty=4.0, days=1)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids, "계획 라인이 없다")
        return run.line_ids[0]

    def test_the_duration_follows_the_mo_quantity_not_the_plan_total(self):
        """**MO 자신의 수량**으로 계산한다 — 계획 전체 수량이 아니다."""
        line = self._line()
        mo = self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": 1.0,
            "date_start": line.start_time,
            "planning_line_id": line.id})
        finish = mo._injection_plan_expected_finish(line.start_time)
        self.assertTrue(finish, "소요 원천이 연결되지 않았다")
        hours = (finish - line.start_time).total_seconds() / 3600.0
        self.assertAlmostEqual(
            hours, 1.0, delta=0.02,
            msg="1개짜리 MO 가 %.2fh 로 계산됐다 — 계획 전체 수량(4개)을 물려받았다"
                % hours)

    def test_the_source_link_is_not_copied_to_a_child_mo(self):
        """복사본(시편·단위 MO)이 부모 원천을 물려받지 않는다."""
        line = self._line()
        parent = self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": 4.0,
            "date_start": line.start_time, "planning_line_id": line.id})
        child = parent.copy({"product_qty": 1.0})
        self.assertFalse(
            child.planning_line_id,
            "복사된 MO 가 계획 원천을 물려받았다 — 부모 수량 소요를 상속한다")

    def test_another_products_plan_line_cannot_be_attached(self):
        """다른 품목의 계획 행을 붙일 수 없다."""
        line = self._line()
        other = self.env["product.product"].create({
            "name": "DS-다른품", "type": "consu", "is_storable": True})
        with self.assertRaises(Exception):
            self.env["mrp.production"].create({
                "product_id": other.id, "product_qty": 1.0,
                "date_start": line.start_time, "planning_line_id": line.id})

    def test_without_a_calendar_the_hook_refuses_instead_of_inventing(self):
        """달력 원천이 없으면 **명시적으로 거부**한다.

        [아스트라 10:14 #3] 「원천 누락/불일치를 `None` 으로 처리해 **코어 60분
        fallback** 으로 돌리는 설계는 … 계획이 우연히 60분이면 통과합니다. …
        **명시적 거부**여야 합니다.」

        앞 판은 `None` 을 돌려 코어 60분으로 넘겼습니다. 「지어내지 않는다」고 적었지만
        코어가 대신 지어내는 것이어서 같은 문제였습니다.
        """
        line = self._line()
        mo = self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": 1.0,
            "date_start": line.start_time, "planning_line_id": line.id})
        self.wc.resource_calendar_id = False
        self.env.company.resource_calendar_id = False
        with self.assertRaises(Exception) as caught:
            mo._injection_plan_expected_finish(line.start_time)
        self.assertIsInstance(caught.exception, UserError)
        self.assertIn("작업 달력", str(caught.exception))

    def test_a_capability_change_does_not_silently_move_a_confirmed_mo(self):
        """[아스트라 10:01] 「**능력 변경 후 재계산**도 원래 확정 계획의 **원천
        보존/재검증 원칙**과 일치해야 합니다.」

        소요를 **현재 능력**에서 계산하므로, 확정된 뒤 사이클타임이 바뀌면 기존
        MO 의 예정 종료가 **조용히 움직일 위험**이 있다. 그러면 안 된다.
        """
        line = self._line()
        mo = self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": 2.0,
            "date_start": line.start_time, "planning_line_id": line.id})
        before = mo._injection_plan_expected_finish(line.start_time)
        self.assertTrue(before, "소요 원천이 연결되지 않았다")
        confirmed_finish = mo.date_finished

        # 확정 뒤 **능력이 바뀐다** (사이클 2배 = 절반 속도)
        self.cap.cycle_time = 7200.0
        self.cap.invalidate_recordset()
        mo.invalidate_recordset()

        after = mo._injection_plan_expected_finish(line.start_time)
        self.capability_change_observation = {
            "before": str(before), "after": str(after),
            "mo_date_finished_before": str(confirmed_finish),
            "mo_date_finished_now": str(mo.date_finished),
        }
        # **저장된 MO 의 예정 종료가 조용히 바뀌면 안 된다.**
        self.assertEqual(
            str(mo.date_finished), str(confirmed_finish),
            "능력이 바뀌자 확정된 MO 의 예정 종료가 조용히 움직였다: %s"
            % self.capability_change_observation)

        # 그리고 **훅 자체는 새 능력을 반영**한다(재계산은 새 기준으로 해야 한다).
        # 즉 「조용히 안 바뀐다」가 훅이 죽어서가 아님을 함께 확인한다 —
        # 사이클 2배면 소요도 2배다.
        self.assertTrue(after, "능력 변경 뒤 훅이 값을 돌려주지 않았다")
        span_before = (before - line.start_time).total_seconds()
        span_after = (after - line.start_time).total_seconds()
        self.assertGreater(
            span_after, span_before,
            "사이클이 2배가 됐는데 재계산 소요가 늘지 않았다 — 훅이 새 원천을 "
            "반영하지 않는다: %s" % self.capability_change_observation)


@tagged("post_install", "-at_install")
class TestPlanSourceRefusalIsExplicit(PlanningCase):
    """[아스트라 10:14 #3] 원천 누락·불일치는 **코어 60분 fallback 이 아니라 거부**다.

    「계획이 우연히 60분이면 통과합니다.」 — 그래서 **딱 60분짜리 계획**으로
    반례를 세운다. 앞 판(`None` 반환)이었다면 이 반례는 **거짓 통과**한다.

    그리고 「**일반 MO 와 정상 라우팅 경로는 보존**하십시오.」 — 대조군으로
    계획과 무관한 MO 와 작업지시가 있는 MO 가 그대로 도는지 함께 본다.
    """

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("RF-기", ton=1000.0)
        self.mold = self._mold("RF-금형", ton=100.0)
        self.cap = self._cap(self.wc, self.mold, cycle=3600.0)   # 1시간에 1개
        self._availability(self.wc, day_h=12.0, night_h=12.0, days=2)

    def _line(self, qty=1.0):
        run = self._run(qty=qty, days=1)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids, "계획 라인이 없다")
        return run.line_ids[0]

    def _plan_linked_mo(self, line, qty=1.0):
        return self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": qty,
            "date_start": line.start_time, "planning_line_id": line.id})

    # ── 반례: 계획이 정확히 60분인데 원천이 사라졌다 ──────────────────────
    def test_a_sixty_minute_plan_with_no_capability_is_refused_not_matched(self):
        """1시간에 1개 × 1개 = **정확히 60분**. 코어 fallback 과 값이 같다.

        원천(능력)을 보관처리하면 앞 판은 `None` → 코어 60분 → **계획과 일치**로
        조용히 통과했다. 이제는 거부해야 한다.
        """
        line = self._line(qty=1.0)
        mo = self._plan_linked_mo(line, qty=1.0)
        # 통과 대조: 원천이 살아 있을 때는 60분이 나온다 (값 자체는 같다)
        healthy = mo._injection_plan_expected_finish(line.start_time)
        self.assertAlmostEqual(
            (healthy - line.start_time).total_seconds() / 3600.0, 1.0, delta=0.02,
            msg="반례 전제가 틀렸다 — 이 계획은 60분이 아니다")

        self.cap.active = False          # 원천이 사라진다
        mo.invalidate_recordset()
        with self.assertRaises(Exception) as caught:
            mo._injection_plan_expected_finish(line.start_time)
        self.assertIsInstance(caught.exception, UserError)
        self.assertIn("능력", str(caught.exception))

    def test_generation_refuses_when_the_capability_disappears(self):
        """계산과 MO 생성 **사이**에 능력이 사라지면 생성이 거부된다."""
        run = self._run(qty=3.0, days=1)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids, "계획 라인이 없다")
        self.cap.active = False
        with self.assertRaises(Exception) as caught:
            run.generate_manufacturing_orders()
        self.assertIsInstance(caught.exception, UserError)

    # ── 대조군: 보존되어야 하는 경로 ────────────────────────────────────
    def test_a_plain_mo_is_not_touched_by_the_refusal(self):
        """계획과 무관한 MO 는 코어 경로 그대로다 — 거부하지 않는다."""
        plain = self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": 5.0,
            "date_start": fields.Datetime.now()})
        self.assertFalse(plain.planning_line_id)
        self.assertIsNone(
            plain._injection_plan_expected_finish(plain.date_start),
            "계획과 무관한 MO 에 사출 계산이 끼어들었다")
        self.assertTrue(plain.date_finished, "코어 정상 계산이 막혔다")

    def test_a_routed_mo_keeps_its_workorder_duration(self):
        """작업지시(라우팅)가 있으면 그 정본을 건드리지 않는다."""
        line = self._line(qty=1.0)
        bom = injection_bom(self.env, {
            "product_tmpl_id": self.inj.product_tmpl_id.id, "product_qty": 1.0,
            "operation_ids": [(0, 0, {
                "name": "RF-공정", "workcenter_id": self.wc.id,
                "time_cycle_manual": 90.0})]})
        mo = self.env["mrp.production"].create({
            "product_id": self.inj.id, "product_qty": 1.0, "bom_id": bom.id,
            "date_start": line.start_time, "planning_line_id": line.id})
        mo.action_confirm()
        self.assertTrue(mo.workorder_ids, "라우팅 전제가 성립하지 않았다")
        self.assertIsNone(
            mo._injection_plan_expected_finish(line.start_time),
            "작업지시가 있는데 사출 계산이 그 정본을 덮으려 했다")

    # ── 원천 연결의 임의 변경 ───────────────────────────────────────────
    def test_a_line_from_another_run_cannot_be_attached(self):
        """[10:14 #3] 「`planning_run_id` 와 line.run 일치」"""
        first = self._line(qty=1.0)
        second = self._line(qty=1.0)
        self.assertNotEqual(first.planning_run_id, second.planning_run_id,
                            "반례 전제가 틀렸다 — 두 계획이 같은 run 이다")
        with self.assertRaises(Exception):
            self.env["mrp.production"].create({
                "product_id": self.inj.id, "product_qty": 1.0,
                "date_start": first.start_time,
                "planning_line_id": first.id,
                "planning_run_id": second.planning_run_id.id})

    def test_the_source_cannot_be_swapped_or_detached_afterwards(self):
        """[10:14 #3] 「**동일 회사·품목의 다른 행 임의 연결/해제**」

        같은 회사·같은 품목의 행이라 품목/회사 제약으로는 걸러지지 않는다.
        """
        first = self._line(qty=1.0)
        second = self._line(qty=1.0)
        self.assertEqual(first.product_id, second.product_id,
                         "반례 전제가 틀렸다 — 품목이 다르면 다른 가드가 잡는다")
        mo = self._plan_linked_mo(first, qty=1.0)
        with self.assertRaises(Exception) as swapped:
            mo.write({"planning_line_id": second.id})
        self.assertIsInstance(swapped.exception, UserError)
        with self.assertRaises(Exception) as detached:
            mo.write({"planning_line_id": False})
        self.assertIsInstance(detached.exception, UserError)
        mo.invalidate_recordset()
        self.assertEqual(mo.planning_line_id, first, "원천이 바뀌어 버렸다")

    def test_the_frozen_capability_cannot_be_rewritten(self):
        """얼린 능력값 자체도 ORM 으로 고쳐 쓸 수 없다 (`readonly` 는 화면만 막는다)."""
        run = self._run(qty=3.0, days=1)
        run.action_calculate_plan()
        run.generate_manufacturing_orders()
        mo = run.line_ids[0].mo_id
        self.assertGreater(mo.planning_hourly_capacity, 0.0,
                           "생성 시점에 능력이 얼려지지 않았다")
        with self.assertRaises(Exception) as caught:
            mo.write({"planning_hourly_capacity": 999.0})
        self.assertIsInstance(caught.exception, UserError)


@tagged("post_install", "-at_install")
class TestConfirmedDurationSurvivesARealWrite(PlanningCase):
    """[아스트라 10:14 #4] 「**이미 생성된 MO 의 `date_start` 등 변경으로 실제
    compute 가 호출될 때**는 생성 함수의 검증이 자동 재실행된다고 볼 수 없습니다.
    이 경로에서 **확정 원천 보존 또는 명시적 재검증**을 구현하고, **실제 write 로
    재현한 시험 결과**를 제시하십시오.」

    그래서 이 시험은 훅을 직접 부르지 않는다. **`date_start` 를 실제로 write** 해
    코어 compute 가 돌게 만든 뒤 저장된 `date_finished` 를 본다.
    """

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("FZ-기", ton=1000.0)
        self.mold = self._mold("FZ-금형", ton=100.0)
        self.cap = self._cap(self.wc, self.mold, cycle=3600.0)   # 1시간에 1개
        self._availability(self.wc, day_h=12.0, night_h=12.0, days=3)
        # The legacy plan fills capacity: the first 12-hour segment contains 12 pieces.
        self.config.inventory_aware_scheduling = False

    def _generated_mo(self, qty=3.0):
        run = self._run(qty=qty, days=1)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids, "계획 라인이 없다")
        run.generate_manufacturing_orders()
        mo = run.line_ids[0].mo_id
        self.assertTrue(mo, "제조오더가 생성되지 않았다")
        self.assertEqual(mo.product_qty, 12.0, "명시한 12시간 첫 구간의 MO 수량")
        return mo

    def test_a_real_date_start_write_does_not_re_price_the_duration(self):
        mo = self._generated_mo(qty=3.0)
        before = (mo.date_finished - mo.date_start).total_seconds()
        self.assertAlmostEqual(before / 3600.0, 12.0, delta=0.05,
                               msg="전제가 틀렸다 — 12개/시간당1개는 12시간이다")

        # 능력 마스터가 **나중에** 바뀐다 (사이클 2배 = 절반 속도)
        self.cap.cycle_time = 7200.0
        self.cap.invalidate_recordset()

        # **실제 write** — 코어 `_compute_date_finished` 가 여기서 돈다
        moved_start = mo.date_start + timedelta(hours=1)
        mo.write({"date_start": moved_start})
        mo.invalidate_recordset()

        # 대조: compute 가 실제로 돌았다 (종료가 시작과 함께 1시간 밀렸다)
        self.assertEqual(
            mo.date_start, moved_start, "시작 시각 write 가 반영되지 않았다")
        after = (mo.date_finished - mo.date_start).total_seconds()
        self.assertAlmostEqual(
            after, before, delta=60.0,
            msg="능력 마스터가 바뀐 뒤 `date_start` write 만으로 확정 MO 의 소요가 "
                "%.2fh → %.2fh 로 다시 매겨졌다" % (before / 3600.0, after / 3600.0))

    def test_the_quantity_still_moves_the_duration(self):
        """능력을 얼려도 **수량 변경에는 정상 반응**한다 (10:01 #1 을 되살리지 않는다).

        소요 **총시간**을 얼렸다면 이 시험이 실패한다 — 그래서 총시간이 아니라
        능력(시간당 개수)을 얼렸다.
        """
        mo = self._generated_mo(qty=3.0)
        before = (mo.date_finished - mo.date_start).total_seconds()
        mo.write({"product_qty": 24.0})
        mo.invalidate_recordset()
        after = (mo.date_finished - mo.date_start).total_seconds()
        self.assertGreater(
            after, before * 1.5,
            "수량을 2배로 올렸는데 소요가 따라오지 않았다 (%.2fh → %.2fh)"
            % (before / 3600.0, after / 3600.0))
