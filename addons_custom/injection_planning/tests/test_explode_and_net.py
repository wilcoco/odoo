"""생산계획 — BOM 전개 필터(G1)·다중 BOM 경고(S4)·순수요 재고 반영 (안전망 배치의 테스트 승격)."""
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestExplodeAndNet(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        P = cls.env["product.product"]
        cls.fin = P.create({"name": "TP-완제품", "default_code": "TP-FIN", "type": "consu"})
        cls.inj = P.create({"name": "TP-사출품", "default_code": "TP-INJ",
                            "type": "consu", "is_storable": True})  # 재고차감 검증용
        cls.out = P.create({"name": "TP-외주부품", "default_code": "TP-OUT", "type": "consu"})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.fin.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [
                (0, 0, {"product_id": cls.inj.id, "product_qty": 1.0}),
                (0, 0, {"product_id": cls.out.id, "product_qty": 4.0}),
            ],
        })
        cls.wc = cls.env["mrp.workcenter"].create({"name": "TP-사출기", "code": "7"})
        mold = cls.env["injection.mold"].create({
            "name": "TP-금형", "code": "TP-MOLD", "product_id": cls.inj.id,
            "cavity_count": 1,
        })
        # capability 보유 = 사출품 판정 폴백 근거(G1)
        cls.env["injection.machine.mold.capability"].create({
            "workcenter_id": cls.wc.id, "mold_id": mold.id, "cycle_time": 45.0,
        })
        d0 = fields.Date.today() + timedelta(days=7)
        cls.demand = cls.env["production.demand"].create({
            "demand_date": d0, "product_id": cls.fin.id,
            "quantity": 100.0, "source": "manual",
        })
        cls.plan_run = cls.env["injection.planning.run"].create({
            "plan_date_from": d0, "plan_date_to": d0,
        })
        cls.plan_run.demand_ids = [(6, 0, cls.demand.ids)]

    def test_01_explode_filters_non_injection(self):
        """[G1] 전개 결과에 사출품만 — 외주부품은 제외된다."""
        issues = []
        pd = self.plan_run.with_context(plan_issues=issues)._explode_bom()
        pids = {pid for (pid, _d) in pd.keys()}
        self.assertIn(self.inj.id, pids)
        self.assertNotIn(self.out.id, pids,
                         "비사출 구성품이 사출 계획 전개에 흘러들면 안 된다")
        # 수량: FIN 100 × INJ 1 = 100
        qty = sum(q for (pid, _d), q in pd.items() if pid == self.inj.id)
        self.assertAlmostEqual(qty, 100.0)

    def test_02_multi_active_bom_warning(self):
        """[S4] 같은 품목에 활성 BOM 2개면 경고가 수집된다(임의 선택 가시화)."""
        self.env["mrp.bom"].create({
            "product_tmpl_id": self.fin.product_tmpl_id.id, "product_qty": 1.0,
            "bom_line_ids": [(0, 0, {"product_id": self.inj.id, "product_qty": 2.0})],
        })
        issues = []
        self.plan_run.with_context(plan_issues=issues)._explode_bom()
        self.assertTrue(any("다중 활성 BOM" in i for i in issues),
                        "다중 활성 BOM 경고가 수집돼야 한다: %s" % issues)

    def test_03_net_requirement_respects_stock(self):
        """순수요는 재고를 차감한다 — 재고 충분하면 생산 불필요."""
        # 사출품 재고를 수요보다 크게
        loc = self.env["stock.location"].search([("usage", "=", "internal")], limit=1)
        self.env["stock.quant"]._update_available_quantity(self.inj, loc, 10000.0)
        pd = self.plan_run._explode_bom()
        net = self.plan_run._calculate_net_requirements(pd)
        inj_net = sum(q for (pid, _d), q in net.items() if pid == self.inj.id)
        self.assertEqual(inj_net, 0.0, "재고가 충분하면 순수요가 0이어야 한다")
