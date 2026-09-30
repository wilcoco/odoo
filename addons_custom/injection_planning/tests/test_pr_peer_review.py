"""아스트라 독립 검토(N-PLANNING-PEER, 2026-09-10) 재현 — 회사 격리와 MO 생성 원자성.

PR08 · PR09 · PR10 과 PR01/PR02 의 '실행 직전 재검증' 이 대상이다.
독립 검토의 인수조건을 그대로 시험으로 옮긴다.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .test_pp03_pp06 import PlanningCase


class CompanyCase(PlanningCase):
    """회사 A 담당자와 회사 B 계획."""

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env["res.company"].create({"name": "PR-회사B"})
        # 시험 실행자(관리자)는 두 회사를 다 볼 수 있어야 B 계획을 세워 둘 수 있다.
        self.env.user.company_ids = [(4, self.company_b.id)]
        self.both = dict(
            self.env.context,
            allowed_company_ids=[self.company_a.id, self.company_b.id])
        self.user_a = self.env["res.users"].create({
            "name": "PR-담당A", "login": "pr_user_a", "email": "pr_a@example.com",
            "company_id": self.company_a.id,
            "company_ids": [(6, 0, [self.company_a.id])],
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("injection_planning.group_planning_user").id,
                self.env.ref("mrp.group_mrp_user").id,
                self.env.ref("stock.group_stock_user").id,
            ])]})
        # 회사 A 의 설비·금형 (기본 시험용)
        self.wc = self._workcenter("PR-기", ton=1200.0)
        self.mold = self._mold("PR-금형", ton=800.0)
        self._cap(self.wc, self.mold)

    def _plan_of_b(self):
        """회사 B 의 설비·금형으로 세운 회사 B 계획.

        회사마다 생산계획 설정을 따로 둔다 — 활성 회사 설정을 빌려 쓰면 B 계획이 A 의
        교대 시간·기본값으로 계산된다. (305 계획 리뷰 (5))
        """
        self.env["injection.planning.config"].create({
            "company_id": self.company_b.id,
            "day_shift_hours": 8.0, "night_shift_hours": 8.0,
            "default_defect_rate": 0.0, "default_initial_scrap": 0,
            "default_min_lot_size": 0, "default_changeover": 0.0})
        # [아스트라 20260912-01 #1] 「최초 19c9089 PASS 로그의 계획일은 9/18(금),
        # 같은 코드 재실행 FAIL 은 9/19(토)였다. … **이 날짜 요인을 통제하지
        # 않았으므로** 'DB 누적상태·후보무관 확정'이라고 보고할 수 없다.」
        #
        # 지적이 맞습니다. `self.day = date.today() + 7` 이라 **실행하는 요일에 따라**
        # 계획일이 토요일이 되고, 회사 B 의 **기본 근무 달력(월~금)** 에는 그날
        # 가동시간이 없어 계획행이 아예 생기지 않았습니다. 그래서 회사격리 본 검사가
        # 시작도 못 했습니다. **DB 누적 상태가 아니라 요일 의존이었습니다.**
        #
        # 이 시험이 보려는 것은 **권한·회사 격리**이지 휴무 차단이 아니므로,
        # 회사 B 에 **명시 합성 가동달력**(7일)을 주어 요일에 무관하게 만듭니다.
        # 휴무 차단 제품 기준은 그대로이고 `TestCalendarAlignment` 등이 따로 봅니다.
        calendar_b = self.env["resource.calendar"].create({
            "name": "PR-회사B 합성 연속가동", "company_id": self.company_b.id,
            "tz": self.company_b.resource_calendar_id.tz or "UTC",
            "attendance_ids": [(5, 0, 0)] + [
                (0, 0, {"name": "연속-%s" % day, "dayofweek": str(day),
                        "hour_from": 0.0, "hour_to": 24.0})
                for day in range(7)]})
        self.company_b.resource_calendar_id = calendar_b.id
        wc_b = self.env["mrp.workcenter"].create({
            "name": "PR-기B", "code": "PR-B", "x_clamping_force_ton": 1200.0,
            "company_id": self.company_b.id,
            # 회사 B 의 작업장은 회사 B 의 근무 달력을 쓴다(기본값은 A 것이라 거절된다)
            "resource_calendar_id": self.company_b.resource_calendar_id.id})
        mold_b = self.env["injection.mold"].create({
            "name": "PR-금형B", "code": "PR-MB", "product_id": self.inj.id,
            "cavity_count": 1, "required_clamping_ton": 800.0,
            "changeover_hours": 0.0, "company_id": self.company_b.id})
        self.env["injection.machine.mold.capability"].create({
            "workcenter_id": wc_b.id, "mold_id": mold_b.id,
            "cycle_time": 45.0, "defect_rate": 0.0, "initial_scrap": 0})
        demand = self.env["production.demand"].create({
            "demand_date": self.day, "product_id": self.fin.id,
            "quantity": 100.0, "source": "manual"})
        run = self.env["injection.planning.run"].with_context(self.both).create({
            "plan_date_from": self.day, "plan_date_to": self.day,
            "company_id": self.company_b.id})
        run.demand_ids = [(6, 0, demand.ids)]
        run.action_calculate_plan()
        self.assertTrue(
            run.line_ids,
            "회사 B 계획에 라인이 생기지 않았다 (계획일 %s %s / 미배정 사유 %s)"
            % (self.day, self.day.strftime("%a"),
               run.unassigned_ids.mapped("reason") or "없음"))
        return run


@tagged("post_install", "-at_install")
class TestCompanyIsolationPR08(CompanyCase):
    """PR08 — 회사 A 만 소속·허용된 담당자가 회사 B 계획을 보고 고칠 수 있었다."""

    def test_other_company_plan_is_not_searchable(self):
        run = self._plan_of_b()
        found = self.env["injection.planning.run"].with_user(self.user_a).search(
            [("id", "=", run.id)])
        self.assertFalse(found, "다른 회사의 계획이 검색에 잡힌다")

    def test_other_company_lines_and_ledgers_are_not_searchable(self):
        run = self._plan_of_b()
        for model, ids in (
            ("injection.planning.line", run.line_ids.ids),
            ("injection.planning.daily.summary", run.summary_ids.ids),
        ):
            if not ids:
                continue
            found = self.env[model].with_user(self.user_a).search([("id", "in", ids)])
            self.assertFalse(found, "%s 가 다른 회사 담당자에게 보인다" % model)

    def test_other_company_line_cannot_be_written(self):
        run = self._plan_of_b()
        line = run.line_ids[0]
        with self.assertRaises(AccessError):
            line.with_user(self.user_a).write({"planned_qty": line.planned_qty + 1})

    def test_other_company_mo_generation_is_refused(self):
        """규칙을 우회해 실행 메서드에 바로 들어와도 막힌다."""
        run = self._plan_of_b()
        with self.assertRaises(AccessError):
            run.with_user(self.user_a).generate_manufacturing_orders()
        with self.assertRaises(AccessError):
            run.with_user(self.user_a).action_confirm_generate_mo()
        self.assertFalse(run.mo_ids)

    def test_generated_mo_belongs_to_the_plan_company(self):
        """회사 B 계획의 MO 는 회사 B 것이다 — 활성 회사가 아니라."""
        run = self._plan_of_b()
        self.assertEqual(run.company_id, self.company_b)
        mos = run.generate_manufacturing_orders()
        self.assertTrue(mos)
        self.assertEqual(set(mos.mapped("company_id")), {self.company_b})


@tagged("post_install", "-at_install")
class TestConfirmTimeRevalidationPR01PR02(CompanyCase):
    """PR01·PR02 — 확정은 계산 시점의 기억이 아니라 실행 직전의 사실로 판단한다."""

    def _ready_plan(self):
        run = self._run(qty=100.0, days=1)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids)
        self.assertFalse(run.line_ids.filtered("fit_unverified"))
        return run

    def test_marker_written_to_false_does_not_open_the_gate(self):
        """PR01 — 미확인 표시를 손으로 지워도 마스터가 비어 있으면 막힌다."""
        self.wc.x_clamping_force_ton = 0.0
        run = self._run(qty=100.0, days=1)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids.filtered("fit_unverified"))
        run.line_ids.write({"fit_unverified": False})   # 표시만 지운다
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids)

    def test_mold_put_into_maintenance_after_calculation_blocks_confirmation(self):
        """PR02 — 계산 뒤 금형을 정비중으로 돌리면 확정이 막힌다."""
        run = self._ready_plan()
        self.mold.state = "maintenance"
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids)

    def test_machine_tonnage_lowered_after_calculation_blocks_confirmation(self):
        """PR02 — 계산 뒤 호기 형체력을 낮춰도 마찬가지."""
        run = self._ready_plan()
        self.wc.x_clamping_force_ton = 500.0
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids)

    def test_capability_removed_after_calculation_blocks_confirmation(self):
        run = self._ready_plan()
        self.env["injection.machine.mold.capability"].search([
            ("workcenter_id", "=", self.wc.id), ("mold_id", "=", self.mold.id),
        ]).active = False
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()

    def test_unchanged_master_still_confirms(self):
        """과차단 방지 — 마스터가 그대로면 예전처럼 확정된다."""
        run = self._ready_plan()
        mos = run.generate_manufacturing_orders()
        self.assertTrue(mos)
        self.assertEqual(run.state, "confirmed")


@tagged("post_install", "-at_install")
class TestMoGenerationAtomicityPR09PR10(CompanyCase):
    """PR09·PR10 — 성공 0 인데 확정, 확정 실패 후 고아 MO, 재시도 중복 생성."""

    def _ready_plan(self):
        run = self._run(qty=100.0, days=1)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids)
        return run

    def _break_confirm(self):
        """`action_confirm` 만 실패시킨다 — 생성은 실제 ORM 그대로.

        돌려주는 스위치를 끄면 그 뒤 호출은 원래대로 동작한다(재시도 시험용).
        """
        MO = type(self.env["mrp.production"])
        original = MO.action_confirm
        switch = {"fail": True}

        def maybe_confirm(inner_self):
            if switch["fail"]:
                raise UserError("SYNTHETIC_CONFIRM_FAILURE")
            return original(inner_self)

        self.patch(MO, "action_confirm", maybe_confirm)
        return switch

    def test_pr09_no_success_means_the_plan_is_not_confirmed(self):
        run = self._ready_plan()
        self._break_confirm()
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertNotEqual(run.state, "confirmed",
                            "MO 를 하나도 만들지 못했는데 계획이 확정됐다")

    def test_pr10_failed_confirmation_leaves_no_orphan_mo(self):
        run = self._ready_plan()
        before = self.env["mrp.production"].search_count([])
        self._break_confirm()
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertEqual(self.env["mrp.production"].search_count([]), before,
                         "확정에 실패한 MO 가 draft 고아로 남았다")
        self.assertFalse(run.line_ids.mapped("mo_id"))

    def test_pr10_retry_after_failure_creates_one_mo_per_line(self):
        """실패 후 정상 재시도해도 라인당 MO 는 하나다."""
        run = self._ready_plan()
        line_count = len(run.line_ids)
        switch = self._break_confirm()
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        switch["fail"] = False
        mos = run.generate_manufacturing_orders()
        self.assertEqual(len(mos), line_count)
        self.assertEqual(len(run.mo_ids), line_count,
                         "재시도가 같은 라인에 MO 를 또 만들었다")
        self.assertEqual(run.state, "confirmed")

    def test_lines_with_an_existing_mo_are_not_candidates(self):
        run = self._ready_plan()
        mos = run.generate_manufacturing_orders()
        self.assertTrue(mos)
        self.assertFalse(run._get_mo_candidate_lines(),
                         "이미 MO 가 붙은 라인이 다시 후보로 잡힌다")


@tagged("post_install", "-at_install")
class TestSchedulingPeerFindings(PlanningCase):
    """PR03~PR07 — 배정·가동시간·순서의 독립 재현.

    스케줄러를 순수요 사전과 함께 직접 부른다(앞단 반올림을 섞지 않기 위해).
    """

    def _run_only(self, days=1):
        return self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=days - 1)})

    def _schedule(self, run, net, days=1):
        run.plan_date_to = self.day + timedelta(days=days - 1)
        return run._schedule(net, run._get_config())

    def test_pr03_pinning_skips_a_machine_that_never_runs(self):
        """PR03 — 가장 빠른 호기가 전 기간 휴무면 차선 호기로 간다."""
        mold = self._mold("PR3-금형")
        fast = self._workcenter("PR3-빠름")
        slow = self._workcenter("PR3-느림")
        self._cap(fast, mold, cycle=180.0)    # 20개/h
        self._cap(slow, mold, cycle=360.0)    # 10개/h
        self._availability(fast, day_h=0.0, night_h=0.0, days=3)
        self._availability(slow, day_h=8.0, night_h=0.0, days=3)
        run = self._run_only(days=3)
        lines, unassigned = self._schedule(
            run, {(self.inj.id, str(self.day)): 100.0}, days=3)
        self.assertTrue(lines, "돌릴 수 있는 차선 호기를 두고 전량 미배정했다")
        self.assertFalse(unassigned)
        self.assertEqual({l["workcenter_id"] for l in lines}, {slow.id})

    def test_pr03_a_calculation_with_no_assignment_does_not_touch_the_mount_master(self):
        """PR03 — 배정 0 인데 실물 장착 이력(last_mold_id)이 바뀌면 안 된다."""
        mold = self._mold("PR3-금형B")
        wc = self._workcenter("PR3-휴무")
        self._cap(wc, mold)
        self._availability(wc, day_h=0.0, night_h=0.0, days=2)
        run = self._run_only(days=2)
        lines, unassigned = self._schedule(
            run, {(self.inj.id, str(self.day)): 100.0}, days=2)
        self.assertFalse(lines)
        self.assertTrue(unassigned)
        avails = self.env["injection.machine.availability"].search(
            [("workcenter_id", "=", wc.id)])
        self.assertFalse(any(avails.mapped("last_mold_id")),
                         "배정이 없는데 장착 금형 마스터가 바뀌었다")

    def test_pr04_overlapping_shifts_are_not_counted_twice(self):
        """PR04 — 주간 08시+16h 와 야간 20시+8h 는 20~24시가 겹친다."""
        wc = self._workcenter("PR4-기")
        self._cap(wc, self._mold("PR4-금형"), cycle=360.0)   # 10개/h
        self._availability(wc, day_h=16.0, night_h=8.0, days=1)
        run = self._run_only()
        issues = []
        lines, _u = self._schedule(
            run.with_context(plan_issues=issues),
            {(self.inj.id, str(self.day)): 200.0})
        config = run._get_config()
        spans = []
        for line in lines:
            start = config.utc_to_shift_local(line["start_time"]).replace(tzinfo=None)
            end = config.utc_to_shift_local(line["end_time"]).replace(tzinfo=None)
            spans.append((start, end))
        spans.sort()
        for earlier, later in zip(spans, spans[1:]):
            self.assertLessEqual(earlier[1], later[0],
                                 "같은 호기의 라인 시간대가 겹친다")
        self.assertTrue(any("가동시간 중복" in i for i in issues),
                        "겹친 설정 사실이 경고로 남지 않았다")

    def test_pr05_the_earlier_due_date_goes_first(self):
        """PR05 — 오늘 필요한 소량이 이틀 뒤 필요한 대량 뒤로 밀리면 안 된다.

        둘 다 기한 안에 넣을 수 있는 입력이다. 적기납품이 최상위 목표다.
        """
        wc = self._workcenter("PR5-기")
        small = self._mold("PR5-소량금형")
        big = self._mold("PR5-대량금형")
        self._cap(wc, small, cycle=36.0)     # 100개/h
        self._cap(wc, big, cycle=36.0)
        self._availability(wc, day_h=8.0, night_h=0.0, days=3)
        later = self.day + timedelta(days=2)
        run = self._run_only(days=3)
        lines, _u = self._schedule(run, {
            (self.inj.id, str(self.day)): 100.0,
            (self.inj.id, str(later)): 900.0,
        }, days=3)
        config = run._get_config()
        today_lines = [l for l in lines if str(l["plan_date"]) == str(self.day)]
        self.assertTrue(today_lines)
        for line in today_lines:
            end = config.utc_to_shift_local(line["end_time"]).replace(tzinfo=None)
            self.assertLessEqual(end.date(), self.day,
                                 "당일 납기 소량이 후납기 대량 뒤로 밀렸다")

    def test_pr06_unknown_mount_state_is_not_read_as_mounted(self):
        """PR06 — 무엇이 물려 있는지 모르는 호기는 금형 설치 시간을 세야 한다."""
        wc = self._workcenter("PR6-기")
        mold = self.env["injection.mold"].create({
            "name": "PR6-금형", "code": "PR6-M", "product_id": self.inj.id,
            "cavity_count": 1, "changeover_hours": 2.0})
        self._cap(wc, mold, cycle=360.0)     # 10개/h
        self._availability(wc, day_h=8.0, night_h=0.0, days=1)
        run = self._run_only()
        lines, unassigned = self._schedule(
            run, {(self.inj.id, str(self.day)): 80.0})
        placed = sum(l["planned_qty"] for l in lines)
        self.assertLess(placed, 80,
                        "설치 2시간을 0으로 세어 8시간에 80개를 전량 배정했다")
        self.assertEqual(placed, 60)
        self.assertTrue(unassigned, "못 넣은 20개가 미배정으로 남지 않았다")
        self.assertTrue(lines[0]["changeover_needed"])
        self.assertAlmostEqual(lines[0]["changeover_hours"], 2.0)

    def test_pr07_explicit_zero_night_hours_stays_zero(self):
        """PR07 — 설정의 야간 0h 가 `or 8.0` 으로 되살아나면 안 된다."""
        self.config.write({"day_shift_hours": 8.0, "night_shift_hours": 0.0})
        wc = self._workcenter("PR7-기")
        self._cap(wc, self._mold("PR7-금형"), cycle=360.0)   # 10개/h
        run = self._run_only()                                # 가동일정 미등록
        lines, unassigned = self._schedule(
            run, {(self.inj.id, str(self.day)): 120.0})
        self.assertFalse(any(l["shift"] == "night" for l in lines),
                         "야간 0h 설정인데 야간 라인이 생겼다")
        self.assertEqual(sum(l["planned_qty"] for l in lines), 80)
        self.assertTrue(unassigned, "잔량 40개가 미배정으로 남지 않았다")
