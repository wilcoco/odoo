from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPqcAggregation(TransactionCase):
    """PQC 자동 생성 — 일반 MO는 FQC 1건, 단위 MO(worksite 설치 시)는 생산 런 단위 묶음."""

    def test_normal_mo_fqc(self):
        product = self.env["product.product"].create({"name": "T-PQC품", "is_storable": True})
        mo = self.env["mrp.production"].create({"product_id": product.id, "product_qty": 1})
        PQC = self.env["iatf.process.inspection"]
        before = PQC.search_count([("production_id", "=", mo.id)])
        mo._create_pqc_inspection()
        self.assertEqual(PQC.search_count([("production_id", "=", mo.id)]), before + 1)
        self.assertEqual(PQC.search([("production_id", "=", mo.id)], limit=1,
                                    order="id desc").inspection_stage, "final")

    def test_unit_mo_run_aggregation(self):
        """단위 MO 폭증 방지 — worksite 미설치 환경이면 skip (필드 부재)."""
        MO = self.env["mrp.production"]
        if "is_ip_unit_mo" not in MO._fields:
            self.skipTest("injection_worksite 미설치 — 단위 MO 경로 없음")
        product = self.env["product.product"].create({"name": "T-사출", "is_storable": True})
        plan = MO.create({"product_id": product.id, "product_qty": 100})
        PQC = self.env["iatf.process.inspection"]
        units = MO.create([{
            "product_id": product.id, "product_qty": 1,
            "is_ip_unit_mo": True, "parent_planning_mo_id": plan.id,
            "date_finished": "2026-07-19 10:00:00",
        } for _ in range(3)])
        units[2].date_finished = "2026-07-20 10:00:00"
        for u in units:
            u._create_pqc_inspection()
        self.assertEqual(PQC.search_count([("production_id", "in", units.ids)]), 0,
                         "단위 MO 개별 검사서 없음")
        runs = PQC.search([("production_id", "=", plan.id)])
        self.assertEqual(len(runs), 2, "생산일별 1건 (19일·20일)")
        day1 = runs.filtered(lambda r: str(r.production_date) == "2026-07-19")
        self.assertEqual(day1.quantity_produced, 2, "같은 런 수량 누적")
        self.assertEqual(day1.article_stage, "first")
