"""제3자 검토(2026-09-10) P1-PP03·PP06 회귀 — 계획 담당자 권한, 설비·금형 물리 제약.

시험은 검토 문서가 제시한 인수 시나리오(UAT-PP03 / UAT-PP06 ①~⑤)를 그대로 따라간다.
"""
from datetime import date, timedelta

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged
from .bom_fixture import injection_bom


class PlanningCase(TransactionCase):
    """사출 계획 한 판을 세우는 공통 고정물."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        P = cls.env["product.product"]
        cls.fin = P.create({"name": "PP-완제품", "default_code": "PP-FIN", "type": "consu"})
        cls.inj = P.create({"name": "PP-사출품", "default_code": "PP-INJ",
                            "type": "consu", "is_storable": True})
        injection_bom(cls.env, {
            "product_tmpl_id": cls.fin.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": cls.inj.id, "product_qty": 1.0})],
        })
        cls.day = date.today() + timedelta(days=7)
        # 스케줄링 자체를 보려는 시험이라 불량률·초기불량·최소로트 같은 가산 규칙은
        # 0 으로 눕힌다. 이것들이 켜져 있으면 배치 시간이 흔들려 무엇을 보고 있는지
        # 알 수 없다(이 규칙들은 별도 시험이 이미 덮고 있다).
        cls.config = cls.env["injection.planning.run"]._get_config()
        cls.config.write({
            "default_defect_rate": 0.0, "default_initial_scrap": 0,
            "default_min_lot_size": 0, "default_changeover": 0.0,
            "day_shift_hours": 8.0, "night_shift_hours": 8.0,
            # [R135] 기존 시험은 이전 알고리즘을 검증한다. 새 방식은 별도 시험이 켠다.
            "sequencing_mode": "legacy",
        })

    def _continuous_calendar(self):
        """24시간 연속 가동 달력.

        배정·배치 규칙을 보는 시험이라 설비 달력의 휴게·휴무를 섞지 않는다. 회사 기본
        달력(주 40시간, 점심 휴게)을 그대로 쓰면 무엇을 보고 있는지 알 수 없다.
        달력과의 정합 자체는 `TestCalendarAlignment` 이 따로 본다.
        """
        cached = getattr(self.__class__, "_cont_cal", None)
        if cached and cached.exists():
            return cached
        cal = self.env["resource.calendar"].create({
            "name": "TEST-연속가동", "tz": self.env["injection.planning.config"]
            ._get_active_shift_config().get_shift_timezone(),
            "attendance_ids": [(5, 0, 0)] + [
                (0, 0, {"name": "연속-%s" % day, "dayofweek": str(day),
                        "hour_from": 0.0, "hour_to": 24.0})
                for day in range(7)]})
        self.__class__._cont_cal = cal
        return cal

    def _workcenter(self, name, ton=0.0):
        return self.env["mrp.workcenter"].create({
            "name": name, "code": name, "x_clamping_force_ton": ton,
            "resource_calendar_id": self._continuous_calendar().id})

    def _mold(self, code, ton=0.0, state="active", product=None):
        return self.env["injection.mold"].create({
            "name": code, "code": code, "product_id": (product or self.inj).id,
            "cavity_count": 1, "required_clamping_ton": ton, "state": state,
            "changeover_hours": 0.0})

    def _cap(self, wc, mold, cycle=45.0, defect=0.0):
        return self.env["injection.machine.mold.capability"].create({
            "workcenter_id": wc.id, "mold_id": mold.id,
            "cycle_time": cycle, "defect_rate": defect, "initial_scrap": 0})

    def _run(self, qty=100.0, days=1):
        demand = self.env["production.demand"].create({
            "demand_date": self.day, "product_id": self.fin.id,
            "quantity": qty, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=days - 1)})
        run.demand_ids = [(6, 0, demand.ids)]
        return run

    def _availability(self, wc, day_h, night_h, days=1, start=None):
        Avail = self.env["injection.machine.availability"]
        first = start or self.day
        for offset in range(days):
            Avail.create({
                "workcenter_id": wc.id, "date": first + timedelta(days=offset),
                "day_shift_hours": day_h, "night_shift_hours": night_h})

    def _unassigned(self, run, reason):
        return run.unassigned_ids.filtered(lambda u: u.reason == reason)


@tagged("post_install", "-at_install")
class TestPlanningUserRightsPP03(PlanningCase):
    """UAT-PP03 — 관리자 권한 없는 계획 담당자가 계산을 끝까지 돌릴 수 있어야 한다."""

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("PP-기1")
        self._cap(self.wc, self._mold("PP-M1"))
        # 검토 문서의 시험 조건 그대로: 계획 담당자 + '필요한 일반 제조/재고 권한만'
        self.planner = self.env["res.users"].create({
            "name": "PP-계획담당", "login": "pp_planner", "email": "pp_planner@example.com",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("injection_planning.group_planning_user").id,
                self.env.ref("mrp.group_mrp_user").id,
                self.env.ref("stock.group_stock_user").id,
            ])]})

    def test_pp03_planner_can_calculate_without_manager_rights(self):
        """관리자 권한 없이도 계산 결과 원장이 남는다.

        예전에는 일별 요약·원재료 소요의 create 권한이 없어 AccessError 로 전체
        계산이 실패했다. 계획 라인 삭제(재계산) 권한도 없었다.
        """
        run = self._run().with_user(self.planner)
        run.action_calculate_plan()
        self.assertEqual(run.state, "review")
        self.assertTrue(run.line_ids, "계획 라인이 생성되지 않았다")
        self.assertTrue(run.summary_ids, "일별 요약이 생성되지 않았다")
        # 초안 복귀 → 재계산까지 같은 권한으로 돈다
        run.action_reset_draft()
        self.assertEqual((run.state, len(run.line_ids)), ("draft", 0))
        run.action_calculate_plan()
        self.assertTrue(run.line_ids)

    def test_pp03_planner_still_cannot_edit_the_results_by_hand(self):
        """넓힌 것은 '계산이 결과를 남기는 것' 하나뿐이다.

        담당자가 산출량·가용재고를 손으로 만들거나 지울 수 있으면 결함을 고친 게
        아니라 옮긴 것이다.
        """
        run = self._run().with_user(self.planner)
        run.action_calculate_plan()
        summary = run.summary_ids[0]
        with self.assertRaises(AccessError):
            summary.write({"planned_qty": 9999.0})
        with self.assertRaises(AccessError):
            summary.unlink()
        with self.assertRaises(AccessError):
            self.env["injection.planning.daily.summary"].with_user(self.planner).create({
                "planning_run_id": run.id, "product_id": self.inj.id,
                "plan_date": self.day, "planned_qty": 9999.0})

    def test_pp03_other_company_plan_is_refused(self):
        """제한 권한은 '자기 회사 계획' 에만 열린다."""
        other = self.env["res.company"].create({"name": "PP-회사B"})
        run = self._run()
        run.company_id = other
        with self.assertRaises(AccessError):
            run.with_user(self.planner).action_calculate_plan()

    def test_pp03_non_planner_is_refused(self):
        """계획 담당자 그룹이 없으면 계산 자체가 거부된다."""
        outsider = self.env["res.users"].create({
            "name": "PP-외부", "login": "pp_outsider", "email": "pp_outsider@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("mrp.group_mrp_user").id,
                                  self.env.ref("stock.group_stock_user").id])]})
        run = self._run()
        with self.assertRaises(AccessError):
            run.with_user(outsider).action_calculate_plan()


@tagged("post_install", "-at_install")
class TestPhysicalConstraintsPP06(PlanningCase):
    """UAT-PP06 ①~⑤ — 물리 제약은 경고가 아니라 차단이고, 차단분은 미배정 큐로 간다.

    배정·배치 규칙 자체를 보는 시험이라 `_schedule` 을 순수요 사전과 함께 직접 부른다.
    앞단(BOM 전개·순수요 배치화)의 반올림이 섞이면 무엇을 보고 있는지 알 수 없다.
    큐가 실제로 기록되는 것까지는 아래 `TestUnassignedQueueWiring` 이 본다.
    """

    def _schedule(self, run, qty, day=None, days=1):
        """순수요 {(사출품, 날짜): 수량} 하나로 스케줄러를 돌린다."""
        run.plan_date_to = (day or self.day) + timedelta(days=days - 1)
        net = {(self.inj.id, str(day or self.day)): float(qty)}
        return run._schedule(net, run._get_config())

    def _run_only(self, days=1):
        return self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=days - 1)})

    @staticmethod
    def _reasons(unassigned):
        return {u["reason"] for u in unassigned}

    def test_pp06_1_clamping_shortfall_blocks_assignment(self):
        """① 금형 요구 1000t, 유일한 호기 500t → 배정 금지.

        예전에는 적합 후보가 하나도 없으면 부적합 후보 전체를 그대로 돌려주어,
        형체력이 모자란 호기에 그대로 배정됐다.
        """
        wc = self._workcenter("PP-500t", ton=500.0)
        self._cap(wc, self._mold("PP-M1000", ton=1000.0))
        lines, unassigned = self._schedule(self._run_only(), 100)
        self.assertFalse(lines, "형체력이 모자란 호기에 배정됐다")
        self.assertEqual(self._reasons(unassigned), {"clamping"})
        self.assertAlmostEqual(sum(u["qty"] for u in unassigned), 100.0)

    def test_pp06_1b_sufficient_clamping_is_still_assigned(self):
        """형체력이 충분하면 예전처럼 배정된다(과차단 방지)."""
        wc = self._workcenter("PP-1200t", ton=1200.0)
        self._cap(wc, self._mold("PP-M1000", ton=1000.0))
        lines, unassigned = self._schedule(self._run_only(), 100)
        self.assertTrue(lines)
        self.assertFalse(unassigned)

    def test_pp06_1c_unregistered_machine_tonnage_is_unverified_not_short(self):
        """호기 형체력이 미등록(0)이면 '부족' 이 아니라 '확인되지 않음' 이다.

        미등록을 부족으로 읽으면 마스터를 채우기 전까지 전 품목이 미배정이 된다.
        배정은 하되 라인에 미확인 표시를 달고, 확정·MO 생성을 막는다
        (`TestUnverifiedFitnessGate`).
        """
        wc = self._workcenter("PP-미등록")
        self._cap(wc, self._mold("PP-M800", ton=800.0))
        run = self._run_only()
        issues = []
        lines, unassigned = self._schedule(run.with_context(plan_issues=issues), 100)
        self.assertTrue(lines)
        self.assertFalse(unassigned)
        self.assertTrue(all(l["fit_unverified"] for l in lines),
                        "확인되지 않은 배정에 표시가 없다")
        self.assertTrue(all(l["fit_note"] for l in lines))
        self.assertTrue(any("적합성 미확인" in i for i in issues))

    def test_pp06_2_unusable_mold_state_blocks_assignment(self):
        """② 정비중·폐기 금형은 후보에서 빠진다."""
        for state in ("maintenance", "retired"):
            with self.subTest(state=state):
                wc = self._workcenter("PP-기-%s" % state)
                self._cap(wc, self._mold("PP-M-%s" % state, state=state))
                lines, unassigned = self._schedule(self._run_only(), 100)
                self.assertFalse(lines, "%s 상태 금형에 배정됐다" % state)
                self.assertEqual(self._reasons(unassigned), {"mold_state"})

    def test_pp06_2b_archived_mold_is_also_excluded(self):
        """보관 해제(active=False)된 금형도 마찬가지다."""
        wc = self._workcenter("PP-기-보관")
        mold = self._mold("PP-M-보관")
        self._cap(wc, mold)
        mold.active = False
        lines, unassigned = self._schedule(self._run_only(), 100)
        self.assertFalse(lines)
        self.assertEqual(self._reasons(unassigned), {"mold_state"})

    def _local_span(self, config, line):
        start = config.utc_to_shift_local(line["start_time"]).replace(tzinfo=None)
        end = config.utc_to_shift_local(line["end_time"]).replace(tzinfo=None)
        return start, end, (end - start).total_seconds() / 3600.0

    def test_pp06_3_long_job_is_split_into_working_windows(self):
        """③ 하루 8h 가동인데 10h 작업 → 허용 구간으로 쪼개고 납기 초과를 표시한다.

        예전에는 남은 시간이 모자라면 다음 날로 통째로 옮겨 붙였다. 그래서 한 줄의
        시작~종료가 비가동 시간대를 가로질렀다.
        """
        wc = self._workcenter("PP-8h")
        self._cap(wc, self._mold("PP-M8h"), cycle=360.0)   # 시간당 10개
        self._availability(wc, day_h=8.0, night_h=0.0, days=3)
        run = self._run_only(days=3)
        lines, unassigned = self._schedule(run, 100, days=3)   # 100개 = 10시간

        self.assertFalse(unassigned, "3일 안에 들어가는 작업이 미배정으로 떨어졌다")
        self.assertGreaterEqual(len(lines), 2,
                                "10시간 작업이 8시간 가동일에 한 줄로 들어갔다")
        config = run._get_config()
        for line in lines:
            _s, _e, span = self._local_span(config, line)
            self.assertLessEqual(span, 8.0 + 1e-6,
                                 "한 줄이 하루 가동시간(8h)을 넘겼다 — 비가동 시간대를 덮었다")
        self.assertEqual(sum(l["planned_qty"] for l in lines), 100)
        # `is_late` 는 저장 후 완료일과 필요일을 비교해 계산한다(P1-PP05). 여기서는
        # 배치 결과가 실제로 다음 날로 넘어갔는지를 본다.
        last_end = max(self._local_span(config, l)[1] for l in lines)
        self.assertGreater(last_end.date(), self.day,
                           "10시간 작업이 8시간 가동일 안에서 끝난 것으로 나온다")

    def test_pp06_3b_day_and_night_are_two_separate_windows(self):
        """주간 8h + 야간 8h 는 연속 16h 가 아니다 — 교대 사이 비가동이 있다.

        예전에는 두 교대 시간을 합쳐 주간 시작부터 연속으로 깔았다. 08 시 시작이면
        16~20 시(비가동)가 작업시간 안에 들어간다.
        """
        wc = self._workcenter("PP-2교대")
        self._cap(wc, self._mold("PP-M2교대"), cycle=360.0)   # 시간당 10개
        self._availability(wc, day_h=8.0, night_h=8.0, days=2)
        run = self._run_only(days=2)
        lines, _u = self._schedule(run, 120, days=2)          # 12시간치
        self.assertGreaterEqual(len(lines), 2, "주·야간에 걸친 작업이 한 줄로 붙었다")
        self.assertEqual({l["shift"] for l in lines}, {"day", "night"})
        config = run._get_config()
        for line in lines:
            _s, _e, span = self._local_span(config, line)
            self.assertLessEqual(span, 8.0 + 1e-6)

    def test_pp06_4_one_physical_mold_is_not_run_on_two_machines(self):
        """④ 같은 실물 금형을 두 호기에 동시에 올리지 않는다.

        금형은 하나뿐인데 capability 가 두 호기에 있으면 예전에는 같은 날 병렬로
        나눠 배정했다.
        """
        mold = self._mold("PP-단일금형")
        wc_a = self._workcenter("PP-기A")
        wc_b = self._workcenter("PP-기B")
        self._cap(wc_a, mold)
        self._cap(wc_b, mold)
        self._availability(wc_a, day_h=8.0, night_h=0.0, days=3)
        self._availability(wc_b, day_h=8.0, night_h=0.0, days=3)
        run = self._run_only(days=3)
        lines, _u = self._schedule(run, 5000, days=3)   # 하루로는 못 끝낼 양
        self.assertTrue(lines)
        self.assertEqual(len({l["workcenter_id"] for l in lines}), 1,
                         "실물 금형 하나가 두 호기에 동시에 배정됐다")

    def test_pp06_4b_two_molds_of_the_same_part_still_run_in_parallel(self):
        """금형이 둘이면 병렬 배정은 그대로다(과차단 방지)."""
        wc_a = self._workcenter("PP-기A")
        wc_b = self._workcenter("PP-기B")
        self._cap(wc_a, self._mold("PP-금형1"))
        self._cap(wc_b, self._mold("PP-금형2"))
        self._availability(wc_a, day_h=8.0, night_h=0.0, days=2)
        self._availability(wc_b, day_h=8.0, night_h=0.0, days=2)
        run = self._run_only(days=2)
        lines, _u = self._schedule(run, 5000, days=2)
        self.assertEqual(len({l["workcenter_id"] for l in lines}), 2,
                         "금형이 둘인데 한 호기에만 배정됐다")

    def test_pp06_5_full_period_shutdown_leaves_the_demand_unassigned(self):
        """⑤ 계획 기간 전체가 휴무면 미배정 예외다.

        예전에는 가용일이 없으면 원래 날짜를 그대로 써서, 쉬는 날에 생산하는
        계획이 만들어졌다.
        """
        wc = self._workcenter("PP-휴무기")
        self._cap(wc, self._mold("PP-M휴무"))
        self._availability(wc, day_h=0.0, night_h=0.0, days=3)
        lines, unassigned = self._schedule(self._run_only(days=3), 100, days=3)
        self.assertFalse(lines, "전 기간 휴무인데 계획 라인이 생겼다")
        self.assertEqual(self._reasons(unassigned), {"no_capacity"})
        self.assertAlmostEqual(sum(u["qty"] for u in unassigned), 100.0)

    def test_pp06_5b_partial_capacity_places_what_fits_and_queues_the_rest(self):
        """가동시간이 일부만 모자라면 들어가는 만큼 배정하고 나머지를 큐로 보낸다."""
        wc = self._workcenter("PP-부족기")
        self._cap(wc, self._mold("PP-M부족"), cycle=360.0)     # 시간당 10개
        self._availability(wc, day_h=8.0, night_h=0.0, days=1)
        lines, unassigned = self._schedule(self._run_only(), 150)   # 15시간치
        self.assertTrue(lines)
        self.assertEqual(sum(l["planned_qty"] for l in lines), 80)
        self.assertEqual(self._reasons(unassigned), {"no_capacity"})
        self.assertAlmostEqual(sum(u["qty"] for u in unassigned), 70.0)

    def test_pp06_no_capability_is_queued(self):
        """이 부품을 만들 조합이 없으면 조용히 사라지지 않는다."""
        other = self.env["product.product"].create({"name": "PP-다른품"})
        self._cap(self._workcenter("PP-다른기"), self._mold("PP-다른금형", product=other))
        lines, unassigned = self._schedule(self._run_only(), 100)
        self.assertFalse(lines)
        self.assertEqual(self._reasons(unassigned), {"no_capability"})


@tagged("post_install", "-at_install")
class TestUnassignedQueueWiring(PlanningCase):
    """미배정 큐가 계산 흐름에 실제로 기록·정리되는지."""

    def setUp(self):
        super().setUp()
        wc = self._workcenter("PP-500t", ton=500.0)
        self._cap(wc, self._mold("PP-M1000", ton=1000.0))

    def test_queue_is_written_by_the_calculation(self):
        run = self._run()
        run.action_calculate_plan()
        self.assertEqual(run.state, "review")
        self.assertFalse(run.line_ids)
        self.assertTrue(run.unassigned_ids)
        self.assertEqual(set(run.unassigned_ids.mapped("reason")), {"clamping"})
        self.assertEqual(run.unassigned_count, len(run.unassigned_ids))
        self.assertEqual(run.unassigned_ids.mapped("product_id"), self.inj)

    def test_recalculation_does_not_pile_the_queue_up(self):
        run = self._run()
        run.action_calculate_plan()
        first = len(run.unassigned_ids)
        self.assertTrue(first)
        run.action_reset_draft()
        self.assertFalse(run.unassigned_ids)
        run.action_calculate_plan()
        self.assertEqual(len(run.unassigned_ids), first)


@tagged("post_install", "-at_install")
class TestUnverifiedFitnessGate(PlanningCase):
    """아스트라 2026-09-10 18:41 — 미등록 적합성 자료는 경고가 아니라 확정 차단이다.

    "0이 부족함을 뜻한다고 단정할 필요 없이 '확인되지 않음' 상태로 구분하면 된다.
     미확인 후보를 초안에서 검토하도록 보여 줄 수 있으나 계획 확정/MO 생성은
     자료 확인 전 차단해야 한다."
    """

    def setUp(self):
        super().setUp()
        # 금형은 800t 을 요구하는데 호기 형체력이 등록되어 있지 않다
        self.wc = self._workcenter("PP-미등록기")
        self._cap(self.wc, self._mold("PP-M800", ton=800.0))

    def test_unverified_line_is_planned_but_flagged(self):
        """초안·검토 단계에서는 보인다 — 배정 자체를 지우지 않는다."""
        run = self._run()
        run.action_calculate_plan()
        self.assertTrue(run.line_ids, "확인 불가를 '부족' 으로 단정해 배정을 지웠다")
        self.assertFalse(run.unassigned_ids)
        self.assertTrue(all(run.line_ids.mapped("fit_unverified")))
        self.assertEqual(run.unverified_line_count, len(run.line_ids))
        self.assertTrue(run.line_ids[0].fit_note)

    def test_confirmation_and_mo_generation_are_blocked(self):
        """확정 위자드도, 위자드를 건너뛴 직접 호출도 막힌다."""
        run = self._run()
        run.action_calculate_plan()
        with self.assertRaises(UserError):
            run.action_confirm_generate_mo()
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids)

    def test_filling_the_master_data_opens_the_gate(self):
        """기준정보를 채우고 다시 계산하면 잠금이 풀린다."""
        run = self._run()
        run.action_calculate_plan()
        self.assertTrue(run.unverified_line_count)
        self.wc.x_clamping_force_ton = 1000.0
        run.action_reset_draft()
        run.action_calculate_plan()
        self.assertEqual(run.unverified_line_count, 0)
        self.assertTrue(run.line_ids)
        # 이제 확정 위자드가 열린다(MO 생성 자체는 별도 시험이 덮는다)
        action = run.action_confirm_generate_mo()
        self.assertEqual(action["res_model"], "injection.generate.mo.wizard")
