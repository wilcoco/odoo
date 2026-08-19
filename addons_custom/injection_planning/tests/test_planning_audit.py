from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPlanningAudit(TransactionCase):
    """계획 엔진 정독 감사 배터리 승격본 — UoM 원단위 정밀·진행 MO 차감·
    사출품 직접 수요·풀캐퍼 정책 고정."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.g = cls.env.ref("uom.product_uom_gram")
        cls.unit = cls.env.ref("uom.product_uom_unit")
        cls.wc = cls.env["mrp.workcenter"].create({"name": "T-사출기"})
        cls.resin = cls.env["product.product"].create({
            "name": "T-수지", "uom_id": cls.kg.id, "uom_po_id": cls.kg.id, "is_storable": True})
        cls.mb = cls.env["product.product"].create({
            "name": "T-마스터배치", "uom_id": cls.kg.id, "uom_po_id": cls.kg.id, "is_storable": True})
        cls.env["injection.planning.config"].create({})

    def _make_inj(self, name, code):
        inj = self.env["product.product"].create({"name": name, "is_storable": True})
        # worksite 미설치 환경(계획 단독 CI)엔 필드가 없음 — capability 보유로도 사출품 판정됨
        if "is_injection_part" in inj.product_tmpl_id._fields:
            inj.product_tmpl_id.is_injection_part = True
        # 원단위는 g 등록 관례 — kg(정밀도 2자리) 등록 시 0.784→0.78 로 저장되는 함정
        self.env["mrp.bom"].create({
            "product_tmpl_id": inj.product_tmpl_id.id, "product_qty": 1,
            "bom_line_ids": [
                (0, 0, {"product_id": self.resin.id, "product_qty": 784, "product_uom_id": self.g.id}),
                (0, 0, {"product_id": self.mb.id, "product_qty": 8, "product_uom_id": self.g.id}),
            ]})
        mold = self.env["injection.mold"].create({"name": name + "금형", "code": code, "product_id": inj.id})
        self.env["injection.machine.mold.capability"].create({
            "workcenter_id": self.wc.id, "mold_id": mold.id,
            "cycle_time": 36.0, "defect_rate": 0.0, "initial_scrap": 0, "active": True})
        return inj

    def _run(self, demand_product, qty, date="2026-08-20"):
        d = self.env["production.demand"].create({
            "demand_date": date, "product_id": demand_product.id,
            "quantity": qty, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": date, "plan_date_to": date,
            "demand_ids": [(6, 0, [d.id])]})
        run.action_calculate_plan()
        return run

    def test_full_chain_uom_and_dedup(self):
        inj = self._make_inj("T-사출품", "TM-1")
        fin = self.env["product.product"].create({"name": "T-완제품", "is_storable": True})
        self.env["mrp.bom"].create({
            "product_tmpl_id": fin.product_tmpl_id.id, "product_qty": 1,
            "bom_line_ids": [(0, 0, {"product_id": inj.id, "product_qty": 2,
                                     "product_uom_id": self.unit.id})]})
        run = self._run(fin, 250)
        planned = sum(run.line_ids.mapped("planned_qty"))
        self.assertEqual(planned, 1600, "풀캐퍼 정책: 100/h×16h")
        reqs = {r.material_id.id: r.required_qty for r in run.material_requirement_ids}
        self.assertAlmostEqual(reqs[self.resin.id], planned * 0.784, places=2,
                               msg="g→kg 원단위 정밀 (반올림 왜곡 금지)")
        self.assertAlmostEqual(reqs[self.mb.id], planned * 0.008, places=3,
                               msg="마스터배치 0.00 결함 회귀 방지")
        run.generate_manufacturing_orders()
        self.assertEqual(len(run.mo_ids), len(run.line_ids))
        # 진행 MO 차감 — 같은 수요 재계획 시 이중 계획 0
        run2 = self._run(fin, 250)
        self.assertEqual(sum(run2.line_ids.mapped("planned_qty")), 0,
                         "진행 MO 미차감 이중 계획 결함 회귀 방지")

    def test_injection_direct_demand_not_lost(self):
        inj2 = self._make_inj("T-사출품2", "TM-2")
        run = self._run(inj2, 300, date="2026-08-25")
        self.assertGreater(sum(run.line_ids.mapped("planned_qty")), 0,
                           "원재료 BOM 보유 사출품의 직접 수요 소실 결함 회귀 방지")
