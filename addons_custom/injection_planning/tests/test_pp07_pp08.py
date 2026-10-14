"""제3자 검토 P1-PP07·PP08 + 아스트라 후속 — 계획 변경 후 파생값, 재발주·재계획 중복.

두 결함의 뿌리는 같다. **계획을 고치거나 다시 세울 때, 이미 나간 실행 결과를 잊는다.**
- PP07: 라인을 고쳐도 원재료 소요·차트·발주량은 계산 당시 값 그대로다.
- PP08: 재계산하면 아직 입고되지 않은 발주와 살아 있는 MO 를 잊고 또 만든다.
"""
from datetime import datetime, time as datetime_time, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import tagged

from .test_pp03_pp06 import PlanningCase
from .bom_fixture import injection_bom


class MaterialCase(PlanningCase):
    """수지 1kg/개 BOM 을 가진 사출품 한 종."""

    def setUp(self):
        super().setUp()
        self.wc = self._workcenter("P78-기", ton=1200.0)
        self.mold = self._mold("P78-금형", ton=100.0)
        self._cap(self.wc, self.mold)
        # 수지는 kg 으로 잡고 발주는 톤으로 나가는 실제 모양을 그대로 쓴다.
        self.kg = self.env.ref("uom.product_uom_kgm")
        self.resin = self.env["product.product"].create({
            "name": "P78-수지", "is_storable": True, "standard_price": 1000.0,
            "uom_id": self.kg.id, "uom_po_id": self.kg.id})
        injection_bom(self.env, {
            "product_tmpl_id": self.inj.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": self.resin.id, "product_qty": 1.0})]})
        self.vendor = self.env["res.partner"].create({"name": "P78-공급사"})
        self.env["product.supplierinfo"].create({
            "partner_id": self.vendor.id, "price": 900.0, "delay": 2,
            "product_tmpl_id": self.resin.product_tmpl_id.id})

    def _calculated(self, qty=100.0, days=1):
        run = self._run(qty=qty, days=days)
        run.action_calculate_plan()
        self.assertTrue(run.line_ids)
        self.assertFalse(run.derived_stale, "방금 계산했는데 재검증 필요로 표시됐다")
        return run

    def _resin_requirement(self, run):
        return run.material_requirement_ids.filtered(
            lambda r: r.material_id == self.resin)


@tagged("post_install", "-at_install")
class TestDerivedStalenessPP07(MaterialCase):
    """UAT-PP07 — 계획을 고치면 파생 결과가 옛 값이라는 사실이 드러나야 한다."""

    def test_editing_a_line_marks_the_derived_results_stale(self):
        run = self._calculated()
        line = run.line_ids[0]
        line.write({"planned_qty": line.planned_qty * 2})
        self.assertTrue(run.derived_stale,
                        "라인을 고쳤는데 파생 결과가 최신인 것처럼 남아 있다")

    def test_status_only_changes_do_not_mark_stale(self):
        """실행 결과(state·mo_id)는 파생값을 바꾸지 않는다 — 과잉 표시 방지."""
        run = self._calculated()
        run.line_ids[0].write({"state": "confirmed"})
        self.assertFalse(run.derived_stale)

    def test_stale_plan_cannot_generate_mo_or_purchase(self):
        run = self._calculated()
        run.line_ids[0].write({"planned_qty": run.line_ids[0].planned_qty * 2})
        with self.assertRaises(UserError):
            run.action_confirm_generate_mo()
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        with self.assertRaises(UserError):
            run.action_create_material_po()

    def test_revalidation_updates_material_requirements(self):
        """재검증하면 원재료 소요가 바뀐 수량을 따라온다."""
        run = self._calculated()
        before = sum(self._resin_requirement(run).mapped("required_qty"))
        self.assertGreater(before, 0.0)
        line = run.line_ids[0]
        line.write({"planned_qty": line.planned_qty + 50})
        run.action_revalidate_requirements()
        self.assertFalse(run.derived_stale)
        after = sum(self._resin_requirement(run).mapped("required_qty"))
        self.assertAlmostEqual(after, before + 50, places=2,
                               msg="원재료 소요가 옛 계획 수량에 머물러 있다")

    def test_revalidation_keeps_existing_purchase_links(self):
        """다시 만든다고 기존 발주 연결을 지우면 안 된다 (조치의 명시 조건)."""
        run = self._calculated()
        run.action_create_material_po()
        req = self._resin_requirement(run)
        self.assertTrue(req.purchase_order_id)
        po = req.purchase_order_id
        run.line_ids[0].write({"planned_qty": run.line_ids[0].planned_qty + 10})
        run.action_revalidate_requirements()
        req = self._resin_requirement(run)
        self.assertEqual(req.purchase_order_id, po,
                         "재검증이 기존 발주 연결을 지웠다")
        self.assertTrue(po.exists())


@tagged("post_install", "-at_install")
class TestNoDuplicateOrderingPP08(MaterialCase):
    """UAT-PP08 — 미입고 발주와 살아 있는 MO 를 잊지 않는다."""

    def test_second_purchase_run_does_not_reorder_the_same_shortage(self):
        run = self._calculated()
        run.action_create_material_po()
        first = run.material_po_ids
        self.assertEqual(len(first), 1)
        with self.assertRaises(UserError):
            run.action_create_material_po()
        self.assertEqual(run.material_po_ids, first, "같은 부족분을 다시 발주했다")

    def test_reordering_is_blocked_even_after_the_link_is_lost(self):
        """연결 필드가 비어도 **실제 발주 잔량**으로 판단한다."""
        run = self._calculated()
        run.action_create_material_po()
        # 재검증·재계산으로 연결이 사라진 상황을 만든다
        self._resin_requirement(run).write({"purchase_order_id": False,
                                            "ordered_qty": 0.0})
        with self.assertRaises(UserError):
            run.action_create_material_po()

    def test_only_the_uncovered_remainder_is_ordered(self):
        """부족분이 늘어나면 **늘어난 만큼만** 추가 발주한다."""
        run = self._calculated()
        run.action_create_material_po()
        first_qty = sum(run.material_po_ids.order_line.mapped("product_qty"))
        line = run.line_ids[0]
        line.write({"planned_qty": line.planned_qty + 40})
        run.action_revalidate_requirements()
        run.action_create_material_po()
        total = sum(run.material_po_ids.order_line.mapped("product_qty"))
        self.assertAlmostEqual(total, first_qty + 40, places=2,
                               msg="이미 발주한 몫까지 다시 발주했다")

    def test_reset_to_draft_is_refused_while_mos_are_alive(self):
        """살아 있는 MO 위에서 재계획하면 같은 수요가 두 번 계획된다."""
        run = self._calculated()
        run.generate_manufacturing_orders()
        self.assertTrue(run.mo_ids)
        with self.assertRaises(UserError):
            run.action_reset_draft()
        self.assertEqual(run.state, "confirmed")

    def test_reset_to_draft_is_allowed_once_the_mos_are_cancelled(self):
        run = self._calculated()
        run.generate_manufacturing_orders()
        run.mo_ids.action_cancel()
        run.action_reset_draft()
        self.assertEqual(run.state, "draft")
        self.assertFalse(run.line_ids)


@tagged("post_install", "-at_install")
class TestCapacityIsNotMisreadPP06Followup(MaterialCase):
    """아스트라 후속 — 이론 최대치를 생산 가능량으로 오인시키지 않는다."""

    def test_theoretical_and_placeable_are_reported_separately(self):
        run = self._calculated()
        self.assertAlmostEqual(
            run.theoretical_qty, run.total_planned_qty + run.unassigned_qty, places=2)
        if run.unassigned_qty:
            self.assertGreater(run.theoretical_qty, run.total_planned_qty,
                               "넣지 못한 수량이 있는데 이론치와 배정량이 같다")

    def test_changeover_hours_are_reported(self):
        """이론치와 배정량의 차이를 만드는 원인이 화면에 남는다."""
        run = self._calculated()
        expected = sum(l.changeover_hours for l in run.line_ids if l.changeover_needed)
        self.assertAlmostEqual(run.changeover_hours_total, expected, places=4)


@tagged("post_install", "-at_install")
class TestMountMasterIsNotWrittenByPlanning(MaterialCase):
    """아스트라 후속 — 계산·초안 배정이 실물 장착 이력을 바꾸면 안 된다."""

    def test_calculation_never_writes_last_mold_id(self):
        Avail = self.env["injection.machine.availability"]
        self._availability(self.wc, day_h=8.0, night_h=8.0, days=2)
        before = {a.id: a.last_mold_id.id for a in Avail.search(
            [("workcenter_id", "=", self.wc.id)])}
        run = self._calculated(qty=100.0, days=2)
        self.assertTrue(run.line_ids)
        after = {a.id: a.last_mold_id.id for a in Avail.search(
            [("workcenter_id", "=", self.wc.id)])}
        self.assertEqual(before, after,
                         "계획 계산이 실물 장착 이력을 갱신했다")

    def test_recalculation_does_not_change_the_next_plans_starting_mold(self):
        """다른 초안 계산이 다음 계획의 시작 금형을 임의로 바꾸지 않는다."""
        Avail = self.env["injection.machine.availability"]
        actual = Avail.create({
            "workcenter_id": self.wc.id, "date": self.day - timedelta(days=1),
            "day_shift_hours": 8.0, "night_shift_hours": 8.0,
            "last_mold_id": self.mold.id})
        self._calculated()
        self._calculated()
        actual.invalidate_recordset()
        self.assertEqual(actual.last_mold_id, self.mold,
                         "재계산이 현장 기록을 덮어썼다")


@tagged("post_install", "-at_install")
class TestPlanningReviewFollowups(MaterialCase):
    """아스트라 275 계획 리뷰 (1)~(4) 후속."""

    # ── (1) 재검증 우회 ──
    def test_stale_flag_cannot_be_lowered_by_hand(self):
        run = self._calculated()
        run.line_ids[0].write({"planned_qty": run.line_ids[0].planned_qty + 1})
        self.assertTrue(run.derived_stale)
        with self.assertRaises(UserError):
            run.write({"derived_stale": False})
        self.assertTrue(run.derived_stale)
        with self.assertRaises(UserError):
            run.action_create_material_po()

    def test_revalidation_is_the_way_to_lower_it(self):
        run = self._calculated()
        run.line_ids[0].write({"planned_qty": run.line_ids[0].planned_qty + 1})
        run.action_revalidate_requirements()
        self.assertFalse(run.derived_stale)

    def test_moving_a_line_marks_both_plans_stale(self):
        """떠난 계획과 도착한 계획 둘 다 파생 결과가 옛 값이 된다."""
        source = self._calculated()
        target = self._calculated()
        source.action_revalidate_requirements()
        target.action_revalidate_requirements()
        self.assertFalse(source.derived_stale)
        self.assertFalse(target.derived_stale)
        source.line_ids[0].write({"planning_run_id": target.id})
        self.assertTrue(source.derived_stale, "라인이 빠져나간 계획에 표시가 없다")
        self.assertTrue(target.derived_stale, "라인을 받은 계획에 표시가 없다")

    # ── (2) 재발주 대사 ──
    def test_partially_received_order_does_not_trigger_a_top_up(self):
        """첫 발주 100 중 40 이 입고되면 남은 60 은 이미 발주된 것이다.

        저장된 부족(100)에서 미입고(60)만 빼면 40 을 또 발주해 총 140 이 된다.
        """
        run = self._calculated()
        run.action_create_material_po()
        req = self._resin_requirement(run)
        required = req.required_qty
        line = run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin)
        self.assertTrue(line)
        # 40% 가 검사를 통과해 재고로 들어왔다고 두고, 발주 잔량도 그만큼 줄인다
        received = required * 0.4
        line.qty_received = received
        self.env["stock.quant"]._update_available_quantity(
            self.resin,
            self.env["stock.warehouse"].search(
                [("company_id", "=", run.company_id.id)], limit=1).lot_stock_id,
            received)
        self.resin.invalidate_recordset()
        with self.assertRaises(UserError):
            run.action_create_material_po()
        total = sum(run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin).mapped("product_qty"))
        self.assertAlmostEqual(total, required, places=2,
                               msg="이미 입고된 몫까지 다시 발주했다")

    def test_outstanding_quantity_is_converted_to_the_stock_uom(self):
        """발주가 톤, 소요가 kg 이면 숫자만 빼서는 1000 배 어긋난다."""
        run = self._calculated()
        run.action_create_material_po()
        line = run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin)
        ton = self.env.ref("uom.product_uom_ton", raise_if_not_found=False)
        if not ton or ton.category_id != self.kg.category_id:
            self.skipTest("이 DB 에 kg 과 같은 범주의 톤 단위가 없다")
        kg_qty = line.product_qty
        line.write({"product_uom": ton.id,
                    "product_qty": kg_qty / 1000.0})
        outstanding = run._outstanding_ordered_qty(self.resin)
        self.assertAlmostEqual(outstanding[self.resin.id][0], kg_qty, places=2,
                               msg="구매 단위를 재고 단위로 환산하지 않았다")

    # ── (3) 명시적 0 ──
    def test_availability_generation_keeps_an_explicit_zero(self):
        self.config.write({"day_shift_hours": 8.0, "night_shift_hours": 0.0})
        run = self._run(qty=100.0, days=2)
        run.action_generate_availability()
        rows = self.env["injection.machine.availability"].search([
            ("workcenter_id", "=", self.wc.id),
            ("date", ">=", run.plan_date_from), ("date", "<=", run.plan_date_to)])
        self.assertTrue(rows)
        self.assertTrue(all(r.night_shift_hours == 0.0 for r in rows),
                        "야간 0h 설정이 일괄 생성에서 8시간으로 되살아났다")

    # ── (4) 회사 범위 ──
    def test_availability_generation_skips_other_companies_machines(self):
        other = self.env["res.company"].create({"name": "P78-회사B"})
        foreign = self.env["mrp.workcenter"].create({
            "name": "P78-타사기", "code": "P78-B", "company_id": other.id,
            "resource_calendar_id": other.resource_calendar_id.id})
        run = self._run(qty=100.0, days=1)
        run.action_generate_availability()
        rows = self.env["injection.machine.availability"].search(
            [("workcenter_id", "=", foreign.id)])
        self.assertFalse(rows, "다른 회사 호기에 우리 계획의 가동일정을 만들었다")


@tagged("post_install", "-at_install")
class TestCalendarAlignment(PlanningCase):
    """아스트라 2026-09-10 19:51 — 계획의 가동창을 실제 설비 달력에 맞춘다.

    계획 08~16(연속 8시간)인데 설비 달력이 08~12 + 13~17(점심 휴게)이면, 8시간 작업의
    실제 종료는 17 시다. 계획과 MO 가 서로 다른 시각을 말하면 날짜별 가용재고 계산이
    그 위에서 돈다.
    """

    def setUp(self):
        super().setUp()
        self.tz = self.config.get_shift_timezone()

    def _calendar(self, name, attendances):
        cal = self.env["resource.calendar"].create({
            "name": name, "tz": self.tz, "attendance_ids": [(5, 0, 0)]})
        for day, hour_from, hour_to in attendances:
            self.env["resource.calendar.attendance"].create({
                "calendar_id": cal.id, "name": "%s-%s" % (name, day),
                "dayofweek": str(day), "hour_from": hour_from, "hour_to": hour_to})
        return cal

    def _machine(self, name, calendar):
        return self.env["mrp.workcenter"].create({
            "name": name, "code": name, "resource_calendar_id": calendar.id})

    def _schedule(self, run, qty, days=1):
        run.plan_date_to = self.day + timedelta(days=days - 1)
        issues = []
        lines, unassigned = run.with_context(plan_issues=issues)._schedule(
            {(self.inj.id, str(self.day)): float(qty)}, run._get_config())
        return lines, unassigned, issues

    def _run_only(self, days=1):
        return self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=days - 1)})

    def test_lunch_break_narrows_the_planning_window(self):
        """달력에 점심 휴게가 있으면 그 시간은 계획에서 빠진다."""
        cal = self._calendar("CAL-휴게", [(d, 8.0, 12.0) for d in range(7)]
                             + [(d, 13.0, 17.0) for d in range(7)])
        wc = self._machine("CAL-기", cal)
        self._cap(wc, self._mold("CAL-금형"), cycle=360.0)      # 10개/h
        self._availability(wc, day_h=8.0, night_h=0.0, days=3)  # 교대는 08~16
        run = self._run_only(days=3)
        lines, _u, issues = self._schedule(run, 80, days=3)     # 8시간치

        self.assertTrue(lines)
        config = run._get_config()
        for line in lines:
            start = config.utc_to_shift_local(line["start_time"]).replace(tzinfo=None)
            end = config.utc_to_shift_local(line["end_time"]).replace(tzinfo=None)
            self.assertFalse(start.hour == 12 or (start < start.replace(hour=13) <= end),
                             "점심 휴게(12~13)가 작업시간에 들어갔다")
        self.assertGreaterEqual(len(lines), 2, "휴게로 끊긴 작업이 한 줄로 붙었다")
        self.assertTrue(any("설비 작업달력" in i for i in issues),
                        "달력이 교대보다 좁다는 사실이 남지 않았다")

    def test_a_continuous_calendar_gets_no_invented_break(self):
        """연속 가동 달력에는 임의 휴게를 넣지 않는다(과차단 방지)."""
        cal = self._calendar("CAL-연속", [(d, 0.0, 24.0) for d in range(7)])
        wc = self._machine("CAL-연속기", cal)
        self._cap(wc, self._mold("CAL-연속금형"), cycle=360.0)
        self._availability(wc, day_h=8.0, night_h=0.0, days=1)
        run = self._run_only()
        lines, unassigned, _i = self._schedule(run, 80)
        self.assertEqual(len(lines), 1, "연속 달력인데 작업이 쪼개졌다")
        self.assertFalse(unassigned)

    def test_no_calendar_means_no_extra_constraint(self):
        wc = self.env["mrp.workcenter"].create({"name": "CAL-무달력", "code": "CAL-N"})
        wc.resource_calendar_id = False
        self._cap(wc, self._mold("CAL-무달력금형"), cycle=360.0)
        self._availability(wc, day_h=8.0, night_h=0.0, days=1)
        run = self._run_only()
        lines, unassigned, _i = self._schedule(run, 80)
        self.assertEqual(len(lines), 1)
        self.assertFalse(unassigned)


@tagged("post_install", "-at_install")
class TestCreatedMoReconciliation(MaterialCase):
    """생성 후 대사 — 계획과 실제가 어긋나면 그 라인은 없던 일이 된다."""

    def test_hook_is_a_no_op_when_everything_matches(self):
        run = self._calculated()
        mos = run.generate_manufacturing_orders()
        self.assertTrue(mos)
        self.assertEqual(len(run.mo_ids), len(run.line_ids))

    def _delay_finish(self, only_line=None):
        """코어가 달력으로 MO 종료를 늦춘 상황을 그대로 만든다."""
        original = self.env["injection.planning.run"].__class__._validate_created_mo

        def shift_finish(inner_self, inner_line, mo):
            if only_line is None or inner_line == only_line:
                mo.date_finished = (
                    inner_line.end_time or mo.date_finished) + timedelta(hours=1)
            return original(inner_self, inner_line, mo)

        self.patch(self.env["injection.planning.run"].__class__,
                   "_validate_created_mo", shift_finish)

    def test_a_later_actual_finish_blocks_every_line(self):
        """설비 달력이 계획보다 좁아 MO 종료가 뒤로 밀리면 보류한다."""
        run = self._calculated()
        self._delay_finish()
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids, "대사에 실패한 MO 가 남았다")
        self.assertNotEqual(run.state, "confirmed")

    def test_only_the_mismatched_line_is_held_back(self):
        """한 라인만 어긋나면 그 라인만 보류하고 나머지는 정상 생성된다."""
        run = self._calculated(qty=400.0, days=2)
        if len(run.line_ids) < 2:
            self.skipTest("이 고정물에서 라인이 하나뿐이다")
        bad = run.line_ids[0]
        self._delay_finish(only_line=bad)
        mos = run.generate_manufacturing_orders()
        self.assertTrue(mos)
        self.assertFalse(bad.mo_id, "대사에 실패한 라인에 MO 가 붙었다")
        self.assertEqual(len(run.mo_ids), len(run.line_ids) - 1)

    def test_company_mismatch_blocks_the_line(self):
        run = self._calculated()
        other = self.env["res.company"].create({"name": "P78-회사C"})
        original = self.env["injection.planning.run"].__class__._validate_created_mo

        def break_company(inner_self, inner_line, mo):
            mo.sudo().company_id = other
            return original(inner_self, inner_line, mo)

        self.patch(self.env["injection.planning.run"].__class__,
                   "_validate_created_mo", break_company)
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids)


@tagged("post_install", "-at_install")
class TestPlanning305Followups(MaterialCase):
    """아스트라 305 계획 리뷰 (1)~(5)."""

    def test_context_flag_no_longer_opens_the_stale_gate(self):
        """(1) 직렬화되는 context Boolean 을 재검증 권한으로 신뢰하지 않는다."""
        run = self._calculated()
        run.line_ids[0].write({"planned_qty": run.line_ids[0].planned_qty + 1})
        self.assertTrue(run.derived_stale)
        with self.assertRaises(UserError):
            run.with_context(injection_planning_revalidated=True).write(
                {"derived_stale": False})
        self.assertTrue(run.derived_stale)

    def test_available_stock_counts_only_the_stock_subtree(self):
        """(2) 검사대기 같은 형제 위치를 가용재고로 세지 않는다.

        `qty_available` 기본 범위는 창고 **view** 하위라 형제 internal 위치가 들어간다.
        """
        run = self._calculated()
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", run.company_id.id)], limit=1)
        pending = self.env["stock.location"].create({
            "name": "P78-검사대기", "usage": "internal",
            "location_id": warehouse.view_location_id.id,
            "company_id": run.company_id.id})
        self.env["stock.quant"]._update_available_quantity(self.resin, pending, 500.0)
        self.resin.invalidate_recordset()

        scoped = run._stock_on_hand(self.resin)
        self.assertAlmostEqual(scoped.get(self.resin.id, 0.0), 0.0, places=2,
                               msg="검사대기 위치 재고를 가용으로 셌다")
        # 대조: Stock 하위에 넣으면 세어야 한다
        self.env["stock.quant"]._update_available_quantity(
            self.resin, warehouse.lot_stock_id, 40.0)
        self.resin.invalidate_recordset()
        scoped = run._stock_on_hand(self.resin)
        self.assertAlmostEqual(scoped.get(self.resin.id, 0.0), 40.0, places=2)

    def test_a_material_that_was_not_short_is_still_re_examined(self):
        """(3) 계산 시점에 넉넉했던 자재가 뒤에 소모되면 다시 부족해진다."""
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        self.env["stock.quant"]._update_available_quantity(
            self.resin, warehouse.lot_stock_id, 100000.0)
        self.resin.invalidate_recordset()
        run = self._calculated()
        req = self._resin_requirement(run)
        self.assertFalse(req.is_short, "시험 전제: 계산 시점엔 넉넉했다")
        # 그 뒤 다른 곳에서 다 써 버렸다
        self.env["stock.quant"]._update_available_quantity(
            self.resin, warehouse.lot_stock_id, -100000.0)
        self.resin.invalidate_recordset()
        run.action_create_material_po()
        self.assertTrue(run.material_po_ids,
                        "저장된 is_short=False 때문에 검사에서 아예 빠졌다")

    def test_new_po_line_uses_the_purchase_uom(self):
        """(4) 재고 kg 수치를 구매 톤에 그대로 넘기지 않는다."""
        ton = self.env.ref("uom.product_uom_ton", raise_if_not_found=False)
        if not ton or ton.category_id != self.kg.category_id:
            self.skipTest("이 DB 에 kg 과 같은 범주의 톤 단위가 없다")
        self.resin.write({"uom_po_id": ton.id})
        self.env["product.supplierinfo"].search(
            [("partner_id", "=", self.vendor.id)]).write({"product_uom": ton.id})
        run = self._calculated()
        required = self._resin_requirement(run).required_qty
        run.action_create_material_po()
        line = run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin)
        self.assertEqual(line.product_uom, ton)
        self.assertAlmostEqual(line.product_qty, required / 1000.0, places=4,
                               msg="kg 수치를 톤 칸에 그대로 넣었다")

    def test_config_and_po_follow_the_plan_company(self):
        """(5) 활성 회사가 아니라 계획의 회사로 설정을 읽고 PO 를 만든다."""
        other = self.env["res.company"].create({"name": "P78-회사D"})
        self.env.user.company_ids = [(4, other.id)]
        config_b = self.env["injection.planning.config"].create({
            "company_id": other.id, "day_shift_hours": 4.0, "night_shift_hours": 0.0})
        run = self._run(qty=100.0, days=1)
        run.company_id = other
        self.assertEqual(run._get_config(), config_b,
                         "다른 회사 계획인데 활성 회사 설정을 읽었다")


@tagged("post_install", "-at_install")
class TestReconciliationTolerance(MaterialCase):
    """아스트라 445 계획 리뷰 (2) — 허용 오차는 저장 정밀도까지다.

    5분을 허용하면 숫자 잔차 회피를 넘어 **실제 5분 납기 지연을 승인**하게 된다.
    업무상 여유는 여기서 정할 일이 아니다.
    """

    def _run_with_delay(self, seconds):
        run = self._calculated()
        original = self.env["injection.planning.run"].__class__._validate_created_mo

        def delay(inner_self, line, mo):
            mo.date_finished = (line.end_time or mo.date_finished) + timedelta(
                seconds=seconds)
            return original(inner_self, line, mo)

        self.patch(self.env["injection.planning.run"].__class__,
                   "_validate_created_mo", delay)
        return run

    def test_sub_second_residue_is_tolerated(self):
        run = self._run_with_delay(0.1)
        self.assertTrue(run.generate_manufacturing_orders())

    def test_one_second_is_tolerated(self):
        run = self._run_with_delay(1)
        self.assertTrue(run.generate_manufacturing_orders())

    def test_one_minute_is_refused(self):
        run = self._run_with_delay(60)
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids)

    def test_five_minutes_is_refused(self):
        """예전에는 이 값이 통과했다 — 실제 지연을 승인하던 자리다."""
        run = self._run_with_delay(300)
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertFalse(run.mo_ids)

    def test_a_full_day_window_ends_on_a_whole_second(self):
        """자정 경계 — 하루를 꽉 채운 작업의 종료에 잔차가 남지 않는다."""
        cal = self.env["resource.calendar"].create({
            "name": "TOL-연속", "attendance_ids": [(5, 0, 0)] + [
                (0, 0, {"name": "연속-%s" % day, "dayofweek": str(day),
                        "hour_from": 0.0, "hour_to": 24.0}) for day in range(7)]})
        wc = self.env["mrp.workcenter"].create({
            "name": "TOL-기", "code": "TOL", "resource_calendar_id": cal.id})
        # 고정물이 미리 만든 빠른 조합을 끄고 이 호기만 남긴다 — 두 호기로 나뉘면
        # '하루를 꽉 채운 작업' 을 보려던 시험이 아니게 된다.
        self.env["injection.machine.mold.capability"].search(
            [("workcenter_id", "=", self.wc.id)]).active = False
        self._cap(wc, self._mold("TOL-금형"), cycle=360.0)   # 10개/h
        self._availability(wc, day_h=24.0, night_h=0.0, days=2)
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day, "plan_date_to": self.day + timedelta(days=1)})
        lines, _u = run._schedule(
            {(self.inj.id, str(self.day)): 240.0}, run._get_config())   # 정확히 24시간
        self.assertTrue(lines)
        config = run._get_config()
        start = config.utc_to_shift_local(lines[0]["start_time"])
        end = config.utc_to_shift_local(lines[-1]["end_time"])
        self.assertEqual(end.microsecond, 0, "종료 시각에 마이크로초 잔차가 남았다")
        self.assertEqual(end.second, 0, "종료 시각에 초 단위 잔차가 남았다")
        self.assertAlmostEqual((end - start).total_seconds(), 24 * 3600, delta=1,
                               msg="24시간치 작업의 시작~종료가 정확히 24시간이 아니다")


@tagged("post_install", "-at_install")
class TestCalendarFallbackScope(PlanningCase):
    """아스트라 445 계획 리뷰 (3) — 되돌림은 명시 가동일정이 있는 날에만."""

    def _machine_with_weekday_calendar(self, name):
        # 월~금 08~16 만 근무하는 달력 (주말 휴무)
        cal = self.env["resource.calendar"].create({
            "name": "%s-평일" % name, "attendance_ids": [(5, 0, 0)] + [
                (0, 0, {"name": "평일-%s" % day, "dayofweek": str(day),
                        "hour_from": 8.0, "hour_to": 16.0}) for day in range(5)]})
        return self.env["mrp.workcenter"].create({
            "name": name, "code": name, "resource_calendar_id": cal.id})

    def _saturday(self):
        day = self.day
        while day.weekday() != 5:
            day += timedelta(days=1)
        return day

    def test_an_explicit_availability_survives_a_closed_calendar_day(self):
        """사람이 '이 토요일 돌린다' 고 적어 두면 그 날은 계획에 남는다."""
        saturday = self._saturday()
        wc = self._machine_with_weekday_calendar("FB-명시")
        self._cap(wc, self._mold("FB-금형"), cycle=360.0)
        self.env["injection.machine.availability"].create({
            "workcenter_id": wc.id, "date": saturday,
            "day_shift_hours": 8.0, "night_shift_hours": 0.0})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": saturday, "plan_date_to": saturday})
        issues = []
        lines, _u = run.with_context(plan_issues=issues)._schedule(
            {(self.inj.id, str(saturday)): 80.0}, run._get_config())
        self.assertTrue(lines, "명시 가동일정을 회사 달력이 취소했다")
        self.assertTrue(any("가동일정을" in i for i in issues))

    def test_without_an_explicit_availability_the_calendar_decides(self):
        """가동일정이 없으면 설정 기본값 창을 되살리지 않는다 — 달력이 정한다."""
        saturday = self._saturday()
        wc = self._machine_with_weekday_calendar("FB-기본")
        self._cap(wc, self._mold("FB-금형2"), cycle=360.0)
        run = self.env["injection.planning.run"].create({
            "plan_date_from": saturday, "plan_date_to": saturday})
        issues = []
        lines, unassigned = run.with_context(plan_issues=issues)._schedule(
            {(self.inj.id, str(saturday)): 80.0}, run._get_config())
        self.assertFalse(lines, "달력이 쉬는 날인데 기본 교대 창이 되살아났다")
        self.assertTrue(unassigned)
        self.assertTrue(any("가동일정 미등록" in i for i in issues))


@tagged("post_install", "-at_install")
class TestMoGenerationIsSerialised(MaterialCase):
    """같은 계획에 대한 동시 MO 생성 — savepoint 만으로는 부족하다.

    savepoint 는 한 요청 안의 원자성만 보장한다. 두 요청이 동시에 들어오면 둘 다 같은
    draft 라인을 후보로 읽고 각자 MO 를 만든다. 계획 행을 잠가 한 줄로 세운다.

    **이 시험이 덮지 못하는 것:** 시험은 하나의 트랜잭션 안에서 돌고 커밋하지 않으므로,
    두 번째 커서에는 여기서 만든 계획 행이 아예 보이지 않는다. 즉 **실제 두 트랜잭션의
    경합 자체는 여기서 재현할 수 없다.** 그래서 (a) 잠금 문장이 MO 를 만들기 **전에**
    그 계획 행에 실제로 걸리는지, (b) 잠금이 풀린 뒤의 요청이 같은 라인을 다시 잡지
    않는지를 본다. DB 수준 경합은 합본 환경에서 따로 확인해야 한다.
    """

    def _record_statements(self):
        """이 트랜잭션이 실제로 보낸 SQL 을 순서대로 모은다."""
        statements = []
        cursor = self.env.cr
        original = cursor.execute

        def spy(query, params=None, log_exceptions=None):
            statements.append(str(query))
            if log_exceptions is None:
                return original(query, params)
            return original(query, params, log_exceptions=log_exceptions)

        self.patch(cursor, "execute", spy)
        return statements

    @staticmethod
    def _index_of(statements, needle, extra=None):
        for index, statement in enumerate(statements):
            if needle in statement and (extra is None or extra in statement):
                return index
        return -1

    def test_lock_helper_locks_this_plan_row(self):
        run = self._calculated()
        statements = self._record_statements()
        run._lock_for_mo_generation()
        locked = [s for s in statements
                  if "injection_planning_run" in s and "FOR UPDATE" in s]
        self.assertTrue(locked, "계획 행에 FOR UPDATE 를 걸지 않았다")

    def test_generation_locks_before_creating_any_mo(self):
        """잠금이 MO 를 만들기 **전에** 걸려야 의미가 있다."""
        run = self._calculated()
        statements = self._record_statements()
        run.generate_manufacturing_orders()
        lock_at = self._index_of(statements, "injection_planning_run", "FOR UPDATE")
        insert_at = self._index_of(statements, 'INSERT INTO "mrp_production"')
        self.assertGreaterEqual(lock_at, 0, "계획 행 잠금이 없었다")
        self.assertGreaterEqual(insert_at, 0, "MO 가 만들어지지 않았다")
        self.assertLess(lock_at, insert_at, "MO 를 만든 뒤에 잠갔다 — 소용이 없다")

    def test_purchase_creation_locks_before_creating_any_order(self):
        run = self._calculated()
        statements = self._record_statements()
        run.action_create_material_po()
        lock_at = self._index_of(statements, "injection_planning_run", "FOR UPDATE")
        insert_at = self._index_of(statements, 'INSERT INTO "purchase_order"')
        self.assertGreaterEqual(lock_at, 0, "계획 행 잠금이 없었다")
        self.assertGreaterEqual(insert_at, 0, "발주서가 만들어지지 않았다")
        self.assertLess(lock_at, insert_at, "발주서를 만든 뒤에 잠갔다 — 소용이 없다")

    def test_a_repeat_request_finds_no_candidates(self):
        """잠금이 풀린 뒤에 온 요청은 이미 MO 가 붙은 라인을 후보로 잡지 않는다."""
        run = self._calculated()
        run.generate_manufacturing_orders()
        made = len(run.mo_ids)
        self.assertTrue(made)
        with self.assertRaises(UserError):
            run.generate_manufacturing_orders()
        self.assertEqual(len(run.mo_ids), made, "같은 라인에 MO 가 더 생겼다")


@tagged("post_install", "-at_install")
class TestIqcPendingIsDisplayOnly(MaterialCase):
    """아스트라 IQC 계약 — 표시만 한다. 이중 차감하지 않고, **0 과 '모른다' 를 구분한다.**"""

    def _install_fake_helper(self, func):
        """검사 모듈이 없는 환경에 계약만 흉내 낸다.

        `self.patch` 는 **있는** 속성만 바꾼다. 여기서는 없는 속성을 새로 다는 것이라
        직접 붙였다 지운다.
        """
        model = type(self.env["stock.quant"])
        setattr(model, "_iqc_pending_quantities", staticmethod(func))
        self.addCleanup(delattr, model, "_iqc_pending_quantities")

    def _pending_location(self):
        """창고 view 하위의 **Stock 형제** 검사대기 위치 (실제 재고를 둘 곳)."""
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        return warehouse, self.env["stock.location"].create({
            "name": "P78-IQC대기", "usage": "internal",
            "location_id": warehouse.view_location_id.id,
            "company_id": self.env.company.id})

    def _helper_reading_real_quants(self, location):
        """실제 quant 를 읽어 계약 형식으로 돌려주는 helper (수치를 지어내지 않는다)."""
        env = self.env

        def real_pending(company_id, product_ids=None, warehouse_id=None):
            domain = [("location_id", "=", location.id),
                      ("company_id", "=", company_id)]
            if product_ids is not None:
                domain.append(("product_id", "in", product_ids))
            rows = {}
            for quant in env["stock.quant"].search(domain):
                row = rows.setdefault(quant.product_id.id, {
                    "company_id": company_id, "product_id": quant.product_id.id,
                    "uom_id": quant.product_id.uom_id.id, "owner_id": False,
                    "quantity": 0.0, "reserved_quantity": 0.0})
                row["quantity"] += quant.quantity
                row["reserved_quantity"] += quant.reserved_quantity
            return list(rows.values())

        return real_pending

    # ── 실제 미해제 수량이 0 보다 큰 시나리오 ──
    def test_real_pending_stock_is_shown_but_never_subtracted(self):
        warehouse, pending = self._pending_location()
        self.env["stock.quant"]._update_available_quantity(self.resin, pending, 40.0)
        self.env["stock.quant"]._update_available_quantity(
            self.resin, warehouse.lot_stock_id, 10.0)
        self.resin.invalidate_recordset()
        self._install_fake_helper(self._helper_reading_real_quants(pending))

        run = self._calculated()
        req = self._resin_requirement(run)
        self.assertEqual(req.iqc_status, "counted")
        self.assertAlmostEqual(req.iqc_pending_qty, 40.0, places=2,
                               msg="실제 검사대기 40 이 화면에 안 나온다")
        # 가용재고에는 Stock 하위 10 만 들어간다
        self.assertAlmostEqual(run._stock_on_hand(self.resin)[self.resin.id], 10.0,
                               places=2, msg="검사대기 40 을 가용으로 셌다")
        # 발주는 소요 − 가용(10) − 미입고발주(0). 검사대기 40 을 다시 빼지 않는다.
        run.action_create_material_po()
        ordered = sum(run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin).mapped("product_qty"))
        self.assertAlmostEqual(ordered, req.required_qty - 10.0, places=2,
                               msg="검사대기 수량이 발주량에서 이중으로 차감됐다")

    def test_a_real_zero_is_reported_as_counted(self):
        """정말 0 인 것과 못 읽은 것은 화면에서 달라야 한다."""
        _warehouse, pending = self._pending_location()
        self._install_fake_helper(self._helper_reading_real_quants(pending))
        run = self._calculated()
        req = self._resin_requirement(run)
        self.assertEqual(req.iqc_status, "counted", "실제 0 인데 '조회 불가' 로 나온다")
        self.assertEqual(req.iqc_pending_qty, 0.0)
        self.assertFalse(req.iqc_status_note)

    # ── 조회 불가 ──
    def test_no_inspection_module_is_reported_as_unavailable(self):
        Quant = self.env["stock.quant"]
        if hasattr(Quant, "_iqc_pending_quantities"):
            self.skipTest("검사 모듈이 설치된 환경이다")
        run = self._calculated()
        req = self._resin_requirement(run)
        self.assertEqual(req.iqc_status, "unavailable",
                         "모듈이 없는데 '집계됨 0' 으로 보인다 — 없는 사실을 단정했다")
        self.assertIn("모듈", req.iqc_status_note or "")
        self.assertEqual(req.iqc_pending_qty, 0.0)

    def test_no_permission_is_reported_as_unavailable(self):
        def denied(company_id, product_ids=None, warehouse_id=None):
            raise AccessError("SYNTHETIC_IQC_ACCESS_DENIED")

        self._install_fake_helper(denied)
        run = self._calculated()
        req = self._resin_requirement(run)
        self.assertEqual(req.iqc_status, "unavailable")
        self.assertIn("권한", req.iqc_status_note or "")

    def test_a_broken_inspection_contract_does_not_stop_planning(self):
        def boom(company_id, product_ids=None, warehouse_id=None):
            raise ValueError("SYNTHETIC_IQC_FAILURE")

        self._install_fake_helper(boom)
        run = self._calculated()
        req = self._resin_requirement(run)
        self.assertTrue(run.material_requirement_ids)
        self.assertEqual(req.iqc_status, "unavailable")
        self.assertEqual(req.iqc_pending_qty, 0.0)

    # ── 계약 경계 ──
    def test_the_helper_is_called_with_the_plans_company_and_products(self):
        calls = []

        def spy(company_id, product_ids=None, warehouse_id=None):
            calls.append((company_id, tuple(sorted(product_ids or ()))))
            return []

        self._install_fake_helper(spy)
        run = self._calculated()
        self.assertTrue(calls)
        company_id, product_ids = calls[-1]
        self.assertEqual(company_id, run.company_id.id,
                         "활성 회사로 조회했다 — 계획의 회사여야 한다")
        self.assertIn(self.resin.id, product_ids)

    def test_a_different_source_unit_is_converted_to_the_stock_uom(self):
        """검사 쪽이 톤으로 알려 줘도 자재 재고 단위(kg)로 담는다."""
        ton = self.env.ref("uom.product_uom_ton", raise_if_not_found=False)
        if not ton or ton.category_id != self.kg.category_id:
            self.skipTest("이 DB 에 kg 과 같은 범주의 톤 단위가 없다")

        def in_tons(company_id, product_ids=None, warehouse_id=None):
            return [{"company_id": company_id, "product_id": self.resin.id,
                     "uom_id": ton.id, "owner_id": False,
                     "quantity": 2.0, "reserved_quantity": 0.5}]

        self._install_fake_helper(in_tons)
        run = self._calculated()
        req = self._resin_requirement(run)
        self.assertAlmostEqual(req.iqc_pending_qty, 2000.0, places=2,
                               msg="톤 수치를 kg 칸에 그대로 담았다")
        self.assertAlmostEqual(req.iqc_reserved_qty, 500.0, places=2)

    # ── 화면 ──
    def test_the_view_shows_the_status_and_hides_the_number_when_unknown(self):
        view = self.env.ref("injection_planning.view_planning_run_form")
        arch = view.arch_db or view.arch
        self.assertIn('name="iqc_status"', arch, "화면에 집계 상태가 없다")
        self.assertIn('invisible="iqc_status != \'counted\'"', arch,
                      "조회 불가일 때 수량 칸을 숨기지 않는다")


@tagged("post_install", "-at_install")
class TestCrossPlanReservation(MaterialCase):
    """아스트라 배정 — 다른 계획이 잡아 둔 창을 다시 쓰지 않는다, KST 검색 경계."""

    def setUp(self):
        super().setUp()
        # 하루 8시간만 도는 호기 하나로 좁혀, 두 계획이 같은 창을 놓고 다투게 한다
        self.env["injection.machine.mold.capability"].search(
            [("workcenter_id", "=", self.wc.id)]).active = False
        self.solo = self._workcenter("XP-기", ton=1200.0)
        self._cap(self.solo, self._mold("XP-금형", ton=100.0), cycle=360.0)  # 10개/h
        self._availability(self.solo, day_h=8.0, night_h=0.0, days=3)

    def _plan(self, qty, days=3):
        demand = self.env["production.demand"].create({
            "demand_date": self.day, "product_id": self.fin.id,
            "quantity": qty, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day,
            "plan_date_to": self.day + timedelta(days=days - 1)})
        run.demand_ids = [(6, 0, demand.ids)]
        run.action_calculate_plan()
        return run

    @staticmethod
    def _spans(run, config):
        return sorted(
            (config.utc_to_shift_local(line.start_time).replace(tzinfo=None),
             config.utc_to_shift_local(line.end_time).replace(tzinfo=None))
            for line in run.line_ids)

    def test_a_committed_plan_blocks_its_window_for_the_next_plan(self):
        first = self._plan(40)
        first.generate_manufacturing_orders()
        self.assertTrue(first.mo_ids)

        second = self._plan(40)
        config = second._get_config()
        taken = self._spans(first, config)
        for start, end in self._spans(second, config):
            for other_start, other_end in taken:
                self.assertFalse(start < other_end and other_start < end,
                                 "다른 계획이 확정한 시간을 다시 썼다")

    def test_an_unconfirmed_plan_does_not_block_anything(self):
        """초안·검토 중인 남의 계획까지 막으면 여러 안을 세워 볼 수 없다."""
        first = self._plan(40)
        self.assertFalse(first.mo_ids)
        second = self._plan(40)
        config = second._get_config()
        self.assertEqual(self._spans(first, config), self._spans(second, config),
                         "확정하지도 않은 계획이 다음 계획을 밀어냈다")

    def test_a_cancelled_mo_releases_the_window(self):
        first = self._plan(40)
        first.generate_manufacturing_orders()
        blocked = self._plan(40)
        config = blocked._get_config()
        before = self._spans(blocked, config)
        first.mo_ids.action_cancel()
        released = self._plan(40)
        self.assertNotEqual(before, self._spans(released, config),
                            "취소한 MO 가 계속 시간을 붙잡고 있다")
        self.assertEqual(self._spans(first, config), self._spans(released, config),
                         "취소 뒤에는 원래 창을 다시 쓸 수 있어야 한다")

    def test_the_reservation_search_uses_a_utc_converted_boundary(self):
        """계획 첫날 **새벽**에 걸친 예약을 놓치지 않는다.

        현지 자정을 그대로 하한으로 쓰면 KST(UTC+9)에서는 9시간 어긋난다. KST 07:00 에
        끝나는 예약은 UTC 로 전날 22:00 이라, 현지 자정(=UTC 그대로 비교) 하한에서는
        검색 범위 밖으로 떨어져 **비어 있는 시간으로 오인**된다.
        """
        company = self.env.company
        calendar = company.resource_calendar_id
        if not calendar:
            self.skipTest("회사 작업 달력이 없어 시간대를 지정할 수 없다")
        calendar.tz = "Asia/Seoul"
        company.invalidate_recordset()

        first = self._plan(40)
        first.generate_manufacturing_orders()
        line = first.line_ids[0]
        config = first._get_config()
        self.assertEqual(config.get_shift_timezone(), "Asia/Seoul")

        # KST 첫날 07:00 에 끝나는 예약 (= UTC 전날 22:00)
        kst_early = datetime.combine(self.day, datetime_time(7, 0))
        line.write({"end_time": config.shift_local_to_utc(kst_early)})

        naive_bound = datetime.combine(self.day, datetime_time.min)
        utc_bound = config.shift_local_to_utc(naive_bound)
        self.assertEqual((naive_bound - utc_bound).total_seconds(), 9 * 3600,
                         "시험 전제: KST 는 UTC 보다 9시간 앞선다")

        Line = self.env["injection.planning.line"]
        base = [("planning_run_id", "=", first.id), ("id", "=", line.id)]
        self.assertFalse(Line.search(base + [("end_time", ">=", naive_bound)]),
                         "시험 전제: 현지 자정 하한에서는 이 예약이 안 잡힌다")
        self.assertEqual(Line.search(base + [("end_time", ">=", utc_bound)]), line,
                         "UTC 로 환산한 하한이 새벽 예약을 놓쳤다")


@tagged("post_install", "-at_install")
class TestCrossPlanConfirmation(MaterialCase):
    """N-CROSSPLAN-CONFIRM — 미리 계산해 둔 두 계획이 같은 창을 각자 확정하던 문제.

    계산 시점의 예약 제외는 그때의 사실이다. 두 계획을 **둘 다 먼저 계산해 두고** 하나를
    확정하면, 다른 계획의 라인은 이미 남의 시간이 된다. 계획 행 잠금은 서로 다른 계획을
    막지 못한다.
    """

    def setUp(self):
        super().setUp()
        self.env["injection.machine.mold.capability"].search(
            [("workcenter_id", "=", self.wc.id)]).active = False
        self.solo = self._workcenter("CC-기", ton=1200.0)
        self.mold_a = self._mold("CC-금형A", ton=100.0)
        self._cap(self.solo, self.mold_a, cycle=360.0)          # 10개/h
        self._availability(self.solo, day_h=8.0, night_h=0.0, days=3)

    def _second_product(self, code):
        product = self.env["product.product"].create(
            {"name": "CC-%s" % code, "default_code": code, "type": "consu",
             "is_storable": True})
        finished = self.env["product.product"].create(
            {"name": "CC-완제품%s" % code, "type": "consu"})
        injection_bom(self.env, {
            "product_tmpl_id": finished.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": product.id, "product_qty": 1.0})]})
        mold = self._mold("CC-금형%s" % code, ton=100.0, product=product)
        self._cap(self.solo, mold, cycle=360.0)
        return finished

    def _plan_for(self, finished, qty=40.0):
        demand = self.env["production.demand"].create({
            "demand_date": self.day, "product_id": finished.id,
            "quantity": qty, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": self.day, "plan_date_to": self.day + timedelta(days=2)})
        run.demand_ids = [(6, 0, demand.ids)]
        run.action_calculate_plan()
        self.assertTrue(run.line_ids)
        self.assertFalse(run.derived_stale)
        return run

    def test_two_precomputed_plans_cannot_both_confirm_the_same_window(self):
        """둘 다 미리 계산 → A 확정 → B 확정 시도는 막혀야 한다."""
        other = self._second_product("CCB")
        plan_a = self._plan_for(self.fin)
        plan_b = self._plan_for(other)
        # 전제: 두 계획이 같은 설비의 겹치는 시간을 잡고 있다
        a_span = (plan_a.line_ids[0].start_time, plan_a.line_ids[0].end_time)
        b_span = (plan_b.line_ids[0].start_time, plan_b.line_ids[0].end_time)
        self.assertEqual(plan_a.line_ids[0].workcenter_id,
                         plan_b.line_ids[0].workcenter_id)
        self.assertTrue(a_span[0] < b_span[1] and b_span[0] < a_span[1],
                        "시험 전제: 두 계획의 시간이 겹쳐야 한다")

        plan_a.generate_manufacturing_orders()
        self.assertTrue(plan_a.mo_ids)

        with self.assertRaises(UserError):
            plan_b.generate_manufacturing_orders()
        self.assertFalse(plan_b.mo_ids, "겹치는 시간에 MO 가 만들어졌다")
        self.assertNotEqual(plan_b.state, "confirmed")
        self.assertFalse(plan_b.line_ids.mapped("mo_id"),
                         "실패한 요청이 계획 링크를 남겼다")

    def test_the_blocked_plan_works_again_after_recalculation(self):
        """막힌 계획은 '초안으로' → 재계산하면 남은 시간으로 배정된다."""
        other = self._second_product("CCC")
        plan_a = self._plan_for(self.fin)
        plan_b = self._plan_for(other)
        plan_a.generate_manufacturing_orders()
        with self.assertRaises(UserError):
            plan_b.generate_manufacturing_orders()

        plan_b.action_reset_draft()
        plan_b.action_calculate_plan()
        if plan_b.line_ids:
            for line in plan_b.line_ids:
                for taken in plan_a.line_ids:
                    self.assertFalse(
                        line.start_time < taken.end_time
                        and taken.start_time < line.end_time,
                        "재계산했는데 여전히 남의 시간을 잡았다")
            plan_b.generate_manufacturing_orders()
            self.assertTrue(plan_b.mo_ids)
        else:
            self.assertTrue(plan_b.unassigned_ids,
                            "배정도 못 하고 미배정도 없다")

    def test_cancelling_the_first_plan_frees_the_window(self):
        other = self._second_product("CCD")
        plan_a = self._plan_for(self.fin)
        plan_b = self._plan_for(other)
        plan_a.generate_manufacturing_orders()
        plan_a.mo_ids.action_cancel()
        # 취소했으니 그 시간은 다시 비어 있다
        plan_b.generate_manufacturing_orders()
        self.assertTrue(plan_b.mo_ids)

    def test_confirmation_bumps_the_shared_resource_version(self):
        """공유 자원 행을 실제로 바꾼다 — Repeatable Read 직렬화의 근거다."""
        plan = self._plan_for(self.fin)
        before = self.solo.x_planning_reservation_seq
        mold_before = self.mold_a.x_planning_reservation_seq
        plan.generate_manufacturing_orders()
        self.solo.invalidate_recordset()
        self.mold_a.invalidate_recordset()
        self.assertGreater(self.solo.x_planning_reservation_seq, before,
                           "설비 행을 바꾸지 않았다 — 낡은 스냅샷이 그대로 통과한다")
        self.assertGreater(self.mold_a.x_planning_reservation_seq, mold_before)

    def test_resending_the_same_plan_stays_idempotent(self):
        plan = self._plan_for(self.fin)
        plan.generate_manufacturing_orders()
        made = len(plan.mo_ids)
        with self.assertRaises(UserError):
            plan.generate_manufacturing_orders()
        self.assertEqual(len(plan.mo_ids), made)


@tagged("post_install", "-at_install")
class TestEarlyMorningReservationReachesTheScheduler(MaterialCase):
    """아스트라 후속 — KST 새벽 예약이 **실제 배정 결과**에까지 이어지는지.

    앞선 시험은 `Line.search` 의 두 하한을 대조했을 뿐이라, 그 하한이 스케줄러의
    가동창에 실제로 반영되는지는 보지 못했다. 여기서는 `_schedule` 을 다시 불러
    새벽에 잡힌 남의 예약만큼 창이 줄어드는지 본다.
    """

    def setUp(self):
        super().setUp()
        calendar = self.env.company.resource_calendar_id
        if not calendar:
            self.skipTest("회사 작업 달력이 없어 시간대를 지정할 수 없다")
        calendar.tz = "Asia/Seoul"
        calendar.write({"attendance_ids": [(5, 0, 0)] + [
            (0, 0, {"name": "연속-%s" % day, "dayofweek": str(day),
                    "hour_from": 0.0, "hour_to": 24.0}) for day in range(7)]})
        self.env.company.invalidate_recordset()
        # 주간 교대를 새벽 06시부터로 두어 '새벽 예약' 이 가동창 안에 들어오게 한다
        self.config.write({"day_shift_start": 6.0, "day_shift_hours": 10.0,
                           "night_shift_hours": 0.0})
        self.env["injection.machine.mold.capability"].search(
            [("workcenter_id", "=", self.wc.id)]).active = False
        self.solo = self._workcenter("EM-기", ton=1200.0)
        self._cap(self.solo, self._mold("EM-금형", ton=100.0), cycle=360.0)  # 10개/h
        self._availability(self.solo, day_h=10.0, night_h=0.0, days=2)

    def test_an_early_morning_reservation_shrinks_the_next_plans_window(self):
        config = self.env["injection.planning.run"]._get_config()
        self.assertEqual(config.get_shift_timezone(), "Asia/Seoul")

        # 남의 계획이 KST 06:00~07:00 을 이미 확정해 두었다
        taken = self._run(qty=10.0, days=1)
        taken.action_calculate_plan()
        self.assertTrue(taken.line_ids)
        taken.generate_manufacturing_orders()
        line = taken.line_ids[0]
        line.write({
            "start_time": config.shift_local_to_utc(
                datetime.combine(self.day, datetime_time(6, 0))),
            "end_time": config.shift_local_to_utc(
                datetime.combine(self.day, datetime_time(7, 0))),
        })

        mine = self.env["injection.planning.run"].create({
            "plan_date_from": self.day, "plan_date_to": self.day})
        lines, _unassigned = mine._schedule(
            {(self.inj.id, str(self.day)): 30.0}, config)
        self.assertTrue(lines, "새벽 예약 때문에 아예 배정을 못 했다")
        first_start = config.utc_to_shift_local(lines[0]["start_time"]).replace(tzinfo=None)
        self.assertGreaterEqual(
            first_start, datetime.combine(self.day, datetime_time(7, 0)),
            "새벽 06~07 시에 잡힌 남의 예약 위에 배정했다")


@tagged("post_install", "-at_install")
class TestPlanningStockScopeIsConsistent(MaterialCase):
    """N-PLANNING-IQC-SCOPE — 계획이 재고를 읽는 곳이 서로 다른 범위를 쓰고 있었다.

    실제 재현: Stock 10 + 검사대기 40 + 소요 30 인데 화면은 available 50 / 부족 아님 /
    일별 50→20 이고 발주는 Stock 10 기준으로 20 을 잡았다. 화면과 발주가 어긋난다.
    기대: available 10 / 부족 20 / 일별 −20 / 발주 20.
    """

    def setUp(self):
        super().setUp()
        self.warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        self.pending_loc = self.env["stock.location"].create({
            "name": "SC-검사대기", "usage": "internal",
            "location_id": self.warehouse.view_location_id.id,
            "company_id": self.env.company.id})
        # 풀 캐퍼 정책이 생산량을 일 가용능력까지 올리므로, 재현 수치(소요 30)를 그대로
        # 보려면 일 가용능력을 30 으로 맞춰야 한다. 하루 1시간 × 시간당 30개.
        self.config.write({"day_shift_hours": 1.0, "night_shift_hours": 0.0})
        self.env["injection.machine.mold.capability"].search(
            [("workcenter_id", "=", self.wc.id)]).active = False
        self.scope_wc = self._workcenter("SC-기", ton=1200.0)
        self._cap(self.scope_wc, self._mold("SC-금형", ton=100.0), cycle=120.0)
        self._availability(self.scope_wc, day_h=1.0, night_h=0.0, days=3)

    def _stock(self, location, qty, product=None):
        self.env["stock.quant"]._update_available_quantity(
            product or self.resin, location, qty)
        (product or self.resin).invalidate_recordset()

    def _requirement_of(self, run, product):
        return run.material_requirement_ids.filtered(
            lambda r: r.material_id == product)

    def _plan_needing(self, resin_qty):
        """수지 `resin_qty` kg 이 필요한 계획 (사출품 1개 = 수지 1kg)."""
        run = self._run(qty=resin_qty, days=1)
        run.action_calculate_plan()
        requirement = run.material_requirement_ids.filtered(
            lambda r: r.material_id == self.resin)
        self.assertTrue(requirement, "시험 전제: 원재료 소요가 잡혀야 한다")
        self.assertAlmostEqual(
            requirement.required_qty, resin_qty, places=2,
            msg="시험 전제: 소요가 %s kg 이어야 재현 수치를 그대로 볼 수 있다" % resin_qty)
        return run

    def test_pending_stock_is_excluded_from_every_view_of_availability(self):
        self._stock(self.warehouse.lot_stock_id, 10.0)
        self._stock(self.pending_loc, 40.0)

        run = self._plan_needing(30.0)
        req = self._requirement_of(run, self.resin)
        self.assertTrue(req)
        # ① 원재료 소요 화면
        self.assertAlmostEqual(req.available_qty, 10.0, places=2,
                               msg="검사대기 40 이 가용재고에 섞였다")
        self.assertTrue(req.is_short, "부족인데 부족 아님으로 나온다")
        # ② 일별 추이의 시작 재고도 같은 값에서 출발한다
        daily = run.material_daily_ids.filtered(
            lambda d: d.material_id == self.resin).sorted("plan_date")
        self.assertTrue(daily)
        self.assertAlmostEqual(daily[0].stock_start, 10.0, places=2,
                               msg="일별 추이가 다른 범위의 재고에서 출발했다")
        # ③ 검사대기는 표시로만 남는다(있으면)
        self.assertAlmostEqual(run._stock_on_hand(self.resin)[self.resin.id], 10.0,
                               places=2)

    def test_the_purchase_matches_what_the_screen_says_is_short(self):
        self._stock(self.warehouse.lot_stock_id, 10.0)
        self._stock(self.pending_loc, 40.0)
        run = self._plan_needing(30.0)
        req = self._requirement_of(run, self.resin)
        shortage = req.shortage_qty
        run.action_create_material_po()
        ordered = sum(run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin).mapped("product_qty"))
        self.assertAlmostEqual(ordered, shortage, places=2,
                               msg="화면의 부족 수량과 실제 발주 수량이 다르다")
        self.assertAlmostEqual(ordered, 20.0, places=2)

    def test_another_companys_stock_never_leaks_in(self):
        """계획 A 를 활성 회사 B 에서 열어도 B 의 재고가 섞이지 않는다."""
        other = self.env["res.company"].create({"name": "SC-회사B"})
        self.env.user.company_ids = [(4, other.id)]
        other_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", other.id)], limit=1)
        if not other_wh:
            self.skipTest("회사 B 의 창고가 자동 생성되지 않았다")
        self._stock(self.warehouse.lot_stock_id, 10.0)
        self._stock(other_wh.lot_stock_id, 100.0)

        run = self._plan_needing(30.0)
        scoped = run.with_context(
            allowed_company_ids=[other.id, self.env.company.id])
        self.assertAlmostEqual(
            scoped._stock_on_hand(self.resin)[self.resin.id], 10.0, places=2,
            msg="다른 회사의 Stock 100 이 계획 A 의 가용재고에 섞였다")

    def test_released_pending_stock_becomes_available(self):
        """검사 합격으로 Stock 으로 옮겨지면 그때부터 가용이다."""
        self._stock(self.warehouse.lot_stock_id, 10.0)
        self._stock(self.pending_loc, 40.0)
        run = self._plan_needing(30.0)
        self.assertTrue(self._requirement_of(run, self.resin).is_short)

        # 합격 해제: 검사대기 → Stock
        self._stock(self.pending_loc, -40.0)
        self._stock(self.warehouse.lot_stock_id, 40.0)
        run.action_revalidate_requirements()
        req = self._requirement_of(run, self.resin)
        self.assertAlmostEqual(req.available_qty, 50.0, places=2)
        self.assertFalse(req.is_short, "해제된 재고가 가용으로 잡히지 않는다")

    def test_a_planner_with_purchase_rights_can_press_the_button(self):
        """[P2] 발주 버튼이 마지막 소요 write 의 ACL 에서 거절되던 문제."""
        buyer = self.env["res.users"].create({
            "name": "SC-계획구매", "login": "sc_planner_buyer",
            "email": "sc_planner_buyer@example.com",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("injection_planning.group_planning_user").id,
                self.env.ref("mrp.group_mrp_user").id,
                self.env.ref("stock.group_stock_user").id,
                self.env.ref("purchase.group_purchase_user").id,
            ])]})
        self._stock(self.warehouse.lot_stock_id, 10.0)
        run = self._plan_needing(30.0).with_user(buyer)
        run.action_create_material_po()
        self.assertTrue(run.material_po_ids, "일반 담당자가 발주하지 못했다")
        req = self._requirement_of(run, self.resin)
        self.assertTrue(req.purchase_order_id, "발주 연결이 기록되지 않았다")

    def test_the_planner_still_cannot_edit_the_requirement_by_hand(self):
        """넓힌 것은 발주 버튼 경로뿐이다."""
        planner = self.env["res.users"].create({
            "name": "SC-계획만", "login": "sc_planner_only",
            "email": "sc_planner_only@example.com",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("injection_planning.group_planning_user").id,
                self.env.ref("mrp.group_mrp_user").id,
                self.env.ref("stock.group_stock_user").id,
            ])]})
        self._stock(self.warehouse.lot_stock_id, 10.0)
        run = self._plan_needing(30.0)
        req = self._requirement_of(run, self.resin)
        with self.assertRaises(AccessError):
            req.with_user(planner).write({"required_qty": 1.0})


@tagged("post_install", "-at_install")
class TestRealIqcHelperContract(MaterialCase):
    """아스트라 후속 — **실제 IQC helper** 와 비제로 실물 대기량으로 대조한다.

    앞선 시험은 계약 형식만 흉내 낸 helper 였다. 검사 모듈이 설치된 환경에서는 진짜
    `stock.quant._iqc_pending_quantities` 로 확인해야 인자·권한·반환형·범위가 맞는지 안다.
    """

    def setUp(self):
        super().setUp()
        Quant = self.env["stock.quant"]
        if not hasattr(Quant, "_iqc_pending_quantities"):
            self.skipTest("검사(IQC) 모듈이 설치되지 않은 환경이다")
        if "iqc_pending" not in self.env["stock.location"]._fields:
            self.skipTest("검사대기 위치 표시가 없는 환경이다")
        from odoo.addons.iatf_incoming_inspection.models.iqc_service import service
        self._service = service
        self.warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        # 검사대기 위치는 입고 서비스만 만든다 — 시험도 그 경로로 만든다.
        self.pending_loc = self._service(self.env["stock.location"]).create({
            "name": "RQ-검사대기", "usage": "internal",
            "location_id": self.warehouse.view_location_id.id,
            "company_id": self.env.company.id,
            "iqc_pending": True, "iqc_warehouse_id": self.warehouse.id})
        self.config.write({"day_shift_hours": 1.0, "night_shift_hours": 0.0})
        self.env["injection.machine.mold.capability"].search(
            [("workcenter_id", "=", self.wc.id)]).active = False
        self.solo = self._workcenter("RQ-기", ton=1200.0)
        self._cap(self.solo, self._mold("RQ-금형", ton=100.0), cycle=120.0)  # 30개/h
        self._availability(self.solo, day_h=1.0, night_h=0.0, days=3)

    def _put(self, location, qty):
        self._service(self.env["stock.quant"])._update_available_quantity(
            self.resin, location, qty)
        self.resin.invalidate_recordset()

    def test_real_pending_quantity_is_shown_and_not_subtracted(self):
        self._put(self.warehouse.lot_stock_id, 10.0)
        self._put(self.pending_loc, 40.0)

        run = self._run(qty=30.0, days=1)
        run.action_calculate_plan()
        req = run.material_requirement_ids.filtered(
            lambda r: r.material_id == self.resin)
        self.assertTrue(req)
        self.assertAlmostEqual(req.required_qty, 30.0, places=2)
        # 실제 helper 가 불려 '집계됨' 으로 잡히고, 대기량이 그대로 보인다
        self.assertEqual(req.iqc_status, "counted")
        self.assertAlmostEqual(req.iqc_pending_qty, 40.0, places=2,
                               msg="실제 검사대기 40 이 집계되지 않았다")
        # 가용은 Stock 하위 10 뿐이고, 검사대기를 다시 빼지 않는다
        self.assertAlmostEqual(req.available_qty, 10.0, places=2)
        self.assertAlmostEqual(req.shortage_qty, 20.0, places=2)
        run.action_create_material_po()
        ordered = sum(run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin).mapped("product_qty"))
        self.assertAlmostEqual(ordered, 20.0, places=2,
                               msg="화면 부족(20)과 발주 수량이 다르다")

    def test_the_real_helper_returns_the_expected_shape(self):
        self._put(self.pending_loc, 40.0)
        rows = self.env["stock.quant"]._iqc_pending_quantities(
            self.env.company.id, product_ids=[self.resin.id])
        self.assertTrue(rows, "실제 helper 가 비제로 대기량을 돌려주지 않았다")
        row = rows[0]
        for key in ("company_id", "product_id", "uom_id", "owner_id",
                    "quantity", "reserved_quantity"):
            self.assertIn(key, row, "계약 필드 %s 가 없다" % key)
        self.assertEqual(row["product_id"], self.resin.id)
        self.assertEqual(row["uom_id"], self.resin.uom_id.id)
        self.assertAlmostEqual(row["quantity"], 40.0, places=2)


@tagged("post_install", "-at_install")
class TestStockScopeNormalisesContext(MaterialCase):
    """N-PLANNING-IQC-SCOPE 후속 — 들어온 `warehouse_id`·`strict` 를 정규화한다.

    계획 재고의 범위 계약은 **계획 회사 창고의 Stock 하위 전체**다. 두 문맥이 남으면
    계약이 깨진다(독립 담당 실측: 각각 available 0 / PO 30).
    """

    def setUp(self):
        super().setUp()
        self.warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        self.config.write({"day_shift_hours": 1.0, "night_shift_hours": 0.0})
        self.env["injection.machine.mold.capability"].search(
            [("workcenter_id", "=", self.wc.id)]).active = False
        self.solo = self._workcenter("NS-기", ton=1200.0)
        self._cap(self.solo, self._mold("NS-금형", ton=100.0), cycle=120.0)  # 30개/h
        self._availability(self.solo, day_h=1.0, night_h=0.0, days=3)

    def _plan(self):
        run = self._run(qty=30.0, days=1)
        run.action_calculate_plan()
        req = run.material_requirement_ids.filtered(
            lambda r: r.material_id == self.resin)
        self.assertAlmostEqual(req.required_qty, 30.0, places=2,
                               msg="시험 전제: 소요 30 이어야 한다")
        return run, req

    def _ordered(self, run):
        return sum(run.material_po_ids.order_line.filtered(
            lambda l: l.product_id == self.resin).mapped("product_qty"))

    def test_a_foreign_warehouse_context_does_not_zero_the_stock(self):
        """반례 ①: 회사 B 창고 문맥이 남으면 교집합이 0 이 되어 available 0 / PO 30."""
        other = self.env["res.company"].create({"name": "NS-회사B"})
        self.env.user.company_ids = [(4, other.id)]
        other_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", other.id)], limit=1)
        if not other_wh:
            self.skipTest("회사 B 의 창고가 자동 생성되지 않았다")
        self.env["stock.quant"]._update_available_quantity(
            self.resin, self.warehouse.lot_stock_id, 10.0)
        self.resin.invalidate_recordset()

        run, _req = self._plan()
        # 전제 — 정규화하지 않으면 정말 0 이 된다(반례가 성립하는지 직접 확인).
        # 코어는 qty_available 캐시를 이 문맥으로 구분하지 않으므로 먼저 비운다.
        raw = self.resin.with_company(self.env.company).with_context(
            location=self.warehouse.lot_stock_id.ids, warehouse_id=other_wh.id)
        raw.invalidate_recordset(["qty_available"])
        self.assertAlmostEqual(raw.qty_available, 0.0, places=2,
                               msg="시험 전제: 정규화 없이는 가용이 0 이어야 한다")
        polluted = run.with_context(warehouse_id=other_wh.id)
        self.assertAlmostEqual(
            polluted._stock_on_hand(self.resin)[self.resin.id], 10.0, places=2,
            msg="다른 회사 창고 문맥 때문에 가용이 0 이 됐다")
        polluted.action_revalidate_requirements()
        polluted.action_create_material_po()
        self.assertAlmostEqual(self._ordered(polluted), 20.0, places=2,
                               msg="가용 0 으로 읽어 30 을 발주했다")

    def test_a_strict_context_still_counts_stock_child_locations(self):
        """반례 ②: Stock **자식 선반**의 10 이 strict 문맥에서 빠져 available 0 / PO 30."""
        shelf = self.env["stock.location"].create({
            "name": "NS-선반", "usage": "internal",
            "location_id": self.warehouse.lot_stock_id.id,
            "company_id": self.env.company.id})
        self.env["stock.quant"]._update_available_quantity(self.resin, shelf, 10.0)
        self.resin.invalidate_recordset()

        run, _req = self._plan()
        # 전제 — strict 를 그대로 두면 Stock 자식 선반의 10 이 빠진다.
        raw = self.resin.with_company(self.env.company).with_context(
            location=self.warehouse.lot_stock_id.ids, strict=True)
        raw.invalidate_recordset(["qty_available"])
        self.assertAlmostEqual(raw.qty_available, 0.0, places=2,
                               msg="시험 전제: strict 를 두면 자식 선반 재고가 빠져야 한다")
        polluted = run.with_context(strict=True)
        self.assertAlmostEqual(
            polluted._stock_on_hand(self.resin)[self.resin.id], 10.0, places=2,
            msg="strict 문맥 때문에 Stock 자식 선반의 재고가 빠졌다")
        polluted.action_revalidate_requirements()
        polluted.action_create_material_po()
        self.assertAlmostEqual(self._ordered(polluted), 20.0, places=2)

    def test_a2_base_on_hand_is_not_polluted_by_strict_cache(self):
        """[R144 테스트 확정] 코어 `qty_available` 캐시 키에 `strict` 가 없어, strict 읽기가 선행되면
        `_stock_scope` 로 정규화한 recordset 에도 0 이 돌아온다. `injection_worksite` 의 override 는
        quant 를 직접 세어 이를 가리므로 **기본 구현**을 직접 호출해 확인한다."""
        from odoo.addons.injection_planning.models.planning_run import PlanningRun as Base
        shelf = self.env["stock.location"].create({
            "name": "NS-선반2", "usage": "internal",
            "location_id": self.warehouse.lot_stock_id.id,
            "company_id": self.env.company.id})
        self.env["stock.quant"]._update_available_quantity(self.resin, shelf, 10.0)
        self.resin.invalidate_recordset()
        run, _req = self._plan()
        # 오염: 같은 location 문맥에서 strict=True 로 먼저 읽어 캐시에 0 을 남긴다
        raw = self.resin.with_company(self.env.company).with_context(
            location=self.warehouse.lot_stock_id.ids, strict=True)
        raw.invalidate_recordset(["qty_available"])
        self.assertAlmostEqual(raw.qty_available, 0.0, places=2)
        scoped = run.with_context(strict=True)._stock_scope(self.resin)
        self.assertNotIn("strict", scoped.env.context)
        self.assertAlmostEqual(Base._planning_on_hand(run, scoped)[self.resin.id], 10.0, places=2,
                               msg="기본 _planning_on_hand 가 strict 로 오염된 캐시를 그대로 돌려줬다")

    def test_both_contexts_together_are_normalised(self):
        other = self.env["res.company"].create({"name": "NS-회사C"})
        self.env.user.company_ids = [(4, other.id)]
        other_wh = self.env["stock.warehouse"].search(
            [("company_id", "=", other.id)], limit=1)
        if not other_wh:
            self.skipTest("회사 C 의 창고가 자동 생성되지 않았다")
        shelf = self.env["stock.location"].create({
            "name": "NS-선반2", "usage": "internal",
            "location_id": self.warehouse.lot_stock_id.id,
            "company_id": self.env.company.id})
        self.env["stock.quant"]._update_available_quantity(self.resin, shelf, 10.0)
        self.resin.invalidate_recordset()
        run, _req = self._plan()
        polluted = run.with_context(warehouse_id=other_wh.id, strict=True)
        self.assertAlmostEqual(
            polluted._stock_on_hand(self.resin)[self.resin.id], 10.0, places=2)

    def test_the_incoming_recordset_and_context_are_not_mutated(self):
        """입력 객체를 바꾸지 않는다 — 정규화한 사본만 돌려준다."""
        run, _req = self._plan()
        source = self.resin.with_context(warehouse_id=123, strict=True)
        before = dict(source.env.context)
        scoped = run._stock_scope(source)
        self.assertEqual(dict(source.env.context), before,
                         "입력 recordset 의 context 가 바뀌었다")
        self.assertNotIn("warehouse_id", scoped.env.context)
        self.assertNotIn("strict", scoped.env.context)
        self.assertIn("location", scoped.env.context)

    def test_an_unpolluted_context_behaves_as_before(self):
        """정상 흐름은 그대로다 — 과차단·과허용 방지."""
        self.env["stock.quant"]._update_available_quantity(
            self.resin, self.warehouse.lot_stock_id, 10.0)
        self.resin.invalidate_recordset()
        run, req = self._plan()
        self.assertAlmostEqual(req.available_qty, 10.0, places=2)
        self.assertAlmostEqual(req.shortage_qty, 20.0, places=2)
        run.action_create_material_po()
        self.assertAlmostEqual(self._ordered(run), 20.0, places=2)
