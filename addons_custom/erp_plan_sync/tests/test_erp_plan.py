from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestErpPlanPush(TransactionCase):
    """오라클 없이 검증 가능한 구간 — 스테이징→수요 반영 멱등·보완 큐 재매칭.
    (실제 수신은 접속정보 필요 — 운영 리허설 항목)"""

    def _line(self, itm, product=False, **vals):
        base = {"ymd": "20260721", "chasu": 1, "line_code": "1", "itm": itm,
                "fno": 1, "plan_date": "2026-07-22", "qty": 10,
                "product_id": product and product.id,
                "state": "matched" if product else "unmatched"}
        base.update(vals)
        return self.env["erp.plan.line"].create(base)

    def test_push_demands_idempotent(self):
        product = self.env["product.product"].create(
            {"name": "T-사출품", "default_code": "86500-TEST01"})
        sync = self.env["erp.plan.sync"].create({"state": "fetched"})
        line = self._line("86500-TEST01", product, sync_id=sync.id)
        sync.action_push_demands()
        self.assertTrue(line.demand_id)
        self.assertEqual(line.demand_id.source, "oracle")
        self.assertEqual(line.demand_id.quantity, 10)
        n = self.env["production.demand"].search_count([("source", "=", "oracle")])
        line.qty = 15
        sync.action_push_demands()  # 재반영 — 신규 생성 없이 수량 갱신
        self.assertEqual(self.env["production.demand"].search_count(
            [("source", "=", "oracle")]), n)
        self.assertEqual(line.demand_id.quantity, 15)

    def test_unmatched_rematch(self):
        line = self._line("86600-NEW001")
        self.assertEqual(line.state, "unmatched")
        line.action_rematch()
        self.assertEqual(line.state, "unmatched", "품목 없으면 그대로 보완 큐")
        self.env["product.product"].create({"name": "신규품", "default_code": "86600-NEW001"})
        line.action_rematch()
        self.assertEqual(line.state, "matched", "품목 등록 후 재매칭")

    def test_staging_unique_key(self):
        self._line("86500-DUP001")
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._line("86500-DUP001")  # 같은 키 중복 — unique 차단

    def test_hourly_push_and_key(self):
        """시간대별 라인 → hourly 수요(hour 포함), 같은 계획일 다른 시간대는 공존."""
        product = self.env["product.product"].create(
            {"name": "T-시간대품", "default_code": "86500-HOUR01"})
        sync = self.env["erp.plan.sync"].create({"state": "fetched"})
        l1 = self._line("86500-HOUR01", product, sync_id=sync.id,
                        demand_type="hourly", hour=3, qty=7)
        l2 = self._line("86500-HOUR01", product, sync_id=sync.id,
                        demand_type="hourly", hour=4, qty=8)  # 같은 날 다른 시간대 — unique 허용
        sync.action_push_demands()
        self.assertEqual(l1.demand_id.demand_type, "hourly")
        self.assertEqual(l1.demand_id.hour, 3)
        self.assertEqual(l2.demand_id.hour, 4)
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._line("86500-HOUR01", product, demand_type="hourly", hour=3)
