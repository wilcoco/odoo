"""[R144 정책 ①②] 수요 확정 수량>0·확정 후 잠금, 계획 번호 = 계획 시작월."""
from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestR144Policies(TransactionCase):

    def test_material_shortage_is_never_negative_and_coverage_capped(self):
        """[R144 관찰 #11] 재고가 소요보다 많으면 부족 0·충족률 100 이지 음수/수만 % 가 아니다."""
        Req = self.env["injection.planning.material.requirement"]
        vals = {"material_id": self.product.id, "required_qty": 10.0, "available_qty": 28000.0}
        for f in ("planning_run_id",):
            if f in Req._fields and Req._fields[f].required:
                vals[f] = self.env["injection.planning.run"].create({"plan_date_from": "2026-10-01", "plan_date_to": "2026-10-01"}).id
        req = Req.new(vals)
        req._compute_shortage()
        self.assertEqual(req.shortage_qty, 0.0); self.assertEqual(req.coverage_rate, 100.0); self.assertFalse(req.is_short)
        short = Req.new(dict(vals, available_qty=4.0)); short._compute_shortage()
        self.assertEqual(short.shortage_qty, 6.0); self.assertTrue(short.is_short)

    def test_mo_shows_planned_mold_and_workcenter(self):
        """[R144 관찰 #7] 실제 장착 금형이 비어 있어도 계획이 정한 금형·사출기는 MO 에서 보인다."""
        run = self.env["injection.planning.run"].create({"plan_date_from": "2026-10-01", "plan_date_to": "2026-10-01"})
        wc = self.env["mrp.workcenter"].create({"name": "R144-WC7"})
        mold = self.env["injection.mold"].create({"name": "R144-M7", "code": "R144-M7", "cavity_count": 1})
        # 계획 연결 MO 는 소요 원천(사출기·금형 능력)을 요구한다 — 정상 가드이므로 갖춰 준다.
        self.env["injection.machine.mold.capability"].create({
            "workcenter_id": wc.id, "mold_id": mold.id, "product_id": self.product.id, "cycle_time": 60.0})
        line = self.env["injection.planning.line"].create({
            "planning_run_id": run.id, "plan_date": "2026-10-01", "workcenter_id": wc.id, "mold_id": mold.id,
            "product_id": self.product.id, "planned_qty": 2.0, "demand_qty": 2.0})
        mo = self.env["mrp.production"].create({"product_id": self.product.id, "product_qty": 2.0,
                                                "planning_run_id": run.id, "planning_line_id": line.id})
        self.assertEqual((mo.planning_mold_id, mo.planning_workcenter_id), (mold, wc))

    def test_generate_mo_wizard_summary_reflects_run(self):
        """[R144 관찰 #6] 위자드 요약은 계획 실행의 초안 라인 수·수량을 그대로 보여준다."""
        run = self.env["injection.planning.run"].create({"plan_date_from": "2026-10-01", "plan_date_to": "2026-10-01"})
        wc = self.env["mrp.workcenter"].create({"name": "R144-WC"})
        mold = self.env["injection.mold"].create({"name": "R144-M", "code": "R144-M"})
        self.env["injection.planning.line"].create([{
            "planning_run_id": run.id, "plan_date": "2026-10-01", "workcenter_id": wc.id, "mold_id": mold.id,
            "product_id": self.product.id, "planned_qty": q, "demand_qty": q} for q in (3.0, 5.0)])
        wiz = self.env["injection.generate.mo.wizard"].with_context(default_planning_run_id=run.id).create({})
        self.assertEqual((wiz.line_count, wiz.total_qty), (2, 8.0))


    def setUp(self):
        super().setUp()
        self.product = self.env["product.product"].create({"name": "R144-FG", "type": "consu"})
        self.Demand = self.env["production.demand"]

    def test_zero_quantity_cannot_be_confirmed(self):
        d = self.Demand.create({"demand_date": "2026-10-01", "product_id": self.product.id, "quantity": 0.0, "source": "manual"})
        with self.assertRaises(UserError):
            d.action_confirm()
        self.assertEqual(d.state, "draft")

    def test_confirmed_demand_locks_quantity_until_reset(self):
        d = self.Demand.create({"demand_date": "2026-10-01", "product_id": self.product.id, "quantity": 4.0, "source": "manual"})
        d.action_confirm()
        with self.assertRaises(UserError):
            d.write({"quantity": 5.0})
        d.write({"notes": "비고는 허용"})
        d.action_reset_draft()
        d.write({"quantity": 5.0})
        self.assertEqual(d.quantity, 5.0)

    def test_run_number_uses_plan_start_month(self):
        run = self.env["injection.planning.run"].create({"plan_date_from": "2026-10-01", "plan_date_to": "2026-10-03"})
        self.assertTrue(run.name.startswith("PP-202610-"), run.name)


from .test_setup_aware_sequencing import SetupAwareCase
from .bom_fixture import injection_bom


@tagged("post_install", "-at_install")
class TestR144ChangeoverManualRouting(SetupAwareCase):
    """[R144 결함 #3] BOM 수동 공정(사이클 60분=1개/시간) + 첫 구간 교체 2h → 교체 라인에도 MO 가 생기고 종료가 계획과 같다."""

    def test_changeover_line_with_manual_routing_gets_mo(self):
        injection_bom(self.env, {"product_tmpl_id": self.prod_b.product_tmpl_id.id, "product_qty": 1.0, "type": "normal",
                                    "operation_ids": [(0, 0, {"name": "사출성형", "workcenter_id": self.wc.id, "time_cycle_manual": 60.0})]})
        self._mount(self.mold_a)                       # 장착 금형 A → B 작업은 교체 2h 가 첫 구간에 포함
        run = self._demands([(self.fin_b, 0, 3)], 1); run.action_calculate_plan()
        first = run.line_ids.filtered("changeover_needed")
        self.assertTrue(first and first[0].changeover_in_span_hours > 0, "전제: 첫 라인 구간에 교체가 포함된다")
        run.generate_manufacturing_orders()
        self.assertTrue(all(l.mo_id for l in run.line_ids), "교체 라인에도 MO 가 생겨야 한다: %s" % [(l.planned_qty, bool(l.mo_id)) for l in run.line_ids])
        mo = first[0].mo_id
        self.assertEqual(len(mo.workorder_ids), 1)
        self.assertLessEqual(abs((mo.date_start - first[0].start_time).total_seconds()), 1)
        self.assertLessEqual(abs((mo.date_finished - first[0].end_time).total_seconds()), 1)
