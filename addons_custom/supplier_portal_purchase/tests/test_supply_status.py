"""공급 현황 화면 — 부품 경로 + 알람 일원화 테스트.

원재료(사일로) 경로는 injection_worksite 가 이 모듈의 의존이 아니므로
여기서 직접 만들 수 없다. 대신 "사일로 모듈이 없어도 부품만으로 화면이
정상 동작하는가"(= soft dependency 가드가 실제로 작동하는가)를 검증하고,
알람 일원화는 부품 쪽에서 replenish_request 가 나가는지로 확인한다.
"""

from datetime import timedelta

from lxml import etree

from odoo import fields
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSupplyStatus(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "TEST-부품공급사",
            "is_supplier_portal": True,
        })
        cls.product = cls.env["product.product"].create({
            "name": "TEST-부품-브라켓",
            "type": "consu",
            "is_storable": True,
        })
        cls.today = fields.Date.context_today(cls.env["supplier.supply.status"])

    def _seed_forecast(self, onhand, incoming, daily, days=10):
        """누적 소요가 가용(보유+입고예정)을 넘어가는 전망을 만든다."""
        Forecast = self.env["supplier.demand.forecast"]
        Forecast.search([("partner_id", "=", self.partner.id)]).unlink()
        available = onhand + incoming
        cum = 0.0
        rows = []
        for i in range(days):
            cum += daily
            rows.append({
                "partner_id": self.partner.id,
                "product_id": self.product.id,
                "date": self.today + timedelta(days=i),
                "qty_required": daily,
                "cum_required": cum,
                "qty_onhand": onhand,
                "qty_incoming": incoming,
                "qty_shortfall": max(0.0, cum - available),
                "snapshot_at": fields.Datetime.now(),
            })
        return Forecast.create(rows)

    # ── 차트 기하 ────────────────────────────────────────────────
    def test_chart_geometry_is_inside_the_box(self):
        """모든 좌표가 플롯 영역 안에 있어야 한다 — 밖으로 나가면 잘려 보인다."""
        Status = self.env["supplier.supply.status"]
        series = [{"label": "01/%02d" % (i + 1), "stock": 100.0 - i * 10,
                   "required": 10.0} for i in range(10)]
        chart = Status._build_chart(series, threshold=30.0)

        x0, y0 = chart["plot_x"], chart["plot_y"]
        x1, y1 = x0 + chart["plot_w"], y0 + chart["plot_h"]
        for pt in chart["points"].split(" "):
            px, py = (float(v) for v in pt.split(","))
            self.assertGreaterEqual(px, x0)
            self.assertLessEqual(px, x1)
            self.assertGreaterEqual(round(py, 3), round(y0, 3))
            self.assertLessEqual(round(py, 3), round(y1, 3))
        for bar in chart["bars"]:
            self.assertGreaterEqual(bar["h"], 0.0)
            self.assertLessEqual(round(bar["y"] + bar["h"], 3), round(y1, 3))
        # 임계선은 값이 범위 안이므로 반드시 그려져야 한다
        self.assertTrue(chart["threshold_y"])
        self.assertGreaterEqual(round(chart["threshold_y"], 3), round(y0, 3))
        self.assertLessEqual(round(chart["threshold_y"], 3), round(y1, 3))

    def test_chart_flat_series_does_not_divide_by_zero(self):
        """값이 전부 같으면 span 이 0 — 여기서 죽으면 화면이 통째로 빈다."""
        Status = self.env["supplier.supply.status"]
        series = [{"label": "d%d" % i, "stock": 0.0, "required": 0.0}
                  for i in range(3)]
        chart = Status._build_chart(series, threshold=0.0)
        self.assertTrue(chart)
        self.assertEqual(len(chart["bars"]), 3)

    def test_chart_empty_series_returns_false(self):
        self.assertFalse(self.env["supplier.supply.status"]._build_chart([]))

    def test_chart_x_labels_are_capped(self):
        """90일을 다 찍으면 겹쳐서 못 읽는다."""
        Status = self.env["supplier.supply.status"]
        series = [{"label": "d%d" % i, "stock": float(i), "required": 1.0}
                  for i in range(90)]
        chart = Status._build_chart(series)
        self.assertLessEqual(len(chart["ticks"]), 9)
        self.assertEqual(len(chart["bars"]), 90)

    # ── 부품 블록 / 알람 ─────────────────────────────────────────
    def test_part_block_curve_crosses_zero_at_shortfall(self):
        """부품의 '잔량' 곡선은 가용 − 누적소요. 부족 시작일에 0을 뚫어야 한다."""
        self._seed_forecast(onhand=100.0, incoming=0.0, daily=20.0, days=10)
        blocks = self.env["supplier.supply.status"].get_portal_status(self.partner)
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block["kind"], "part")
        self.assertEqual(block["threshold"], 0.0)
        stocks = [s["stock"] for s in block["series"]]
        # 100 - 20*k : 5일차(index 4)에 0, 6일차부터 음수
        self.assertEqual(stocks[0], 80.0)
        self.assertEqual(stocks[4], 0.0)
        self.assertLess(stocks[5], 0.0)

    def test_part_alert_is_danger_when_shortfall_is_imminent(self):
        """부족 시작이 7일 이내면 danger — 부품에도 즉각 신호가 가야 한다."""
        self._seed_forecast(onhand=60.0, incoming=0.0, daily=20.0, days=10)
        block = self.env["supplier.supply.status"].get_portal_status(self.partner)[0]
        alert = block["alert"]
        self.assertEqual(alert["level"], "danger")
        # 발주서(명시적 보충 요청)는 부품에는 없다 — 여기가 원재료와의 유일한 차이
        self.assertFalse(alert["has_request"])
        self.assertEqual(alert["due_date"], self.today + timedelta(days=3))

    def test_part_alert_is_warning_when_shortfall_is_far(self):
        # 하루 10, 가용 200 → 20일차에 부족 (7일 밖)
        self._seed_forecast(onhand=200.0, incoming=0.0, daily=10.0, days=25)
        block = self.env["supplier.supply.status"].get_portal_status(self.partner)[0]
        self.assertEqual(block["alert"]["level"], "warning")

    def test_part_alert_is_ok_without_shortfall(self):
        self._seed_forecast(onhand=1000.0, incoming=0.0, daily=10.0, days=10)
        block = self.env["supplier.supply.status"].get_portal_status(self.partner)[0]
        self.assertEqual(block["alert"]["level"], "ok")
        self.assertFalse(block["alert"]["has_request"])

    def test_incoming_stock_delays_the_shortfall(self):
        """입고 예정을 가용에 안 더하면 있지도 않은 부족을 협력사에 알리게 된다."""
        self._seed_forecast(onhand=60.0, incoming=0.0, daily=20.0, days=10)
        without = self.env["supplier.supply.status"].get_portal_status(self.partner)[0]
        self._seed_forecast(onhand=60.0, incoming=140.0, daily=20.0, days=10)
        with_incoming = self.env["supplier.supply.status"].get_portal_status(self.partner)[0]
        self.assertEqual(without["alert"]["level"], "danger")
        self.assertEqual(with_incoming["alert"]["level"], "ok")

    # ── 알람 일원화 ──────────────────────────────────────────────
    def test_cron_notifies_non_material_supplier(self):
        """사용자 요구: '다른 발주사에게도 같은 형태의 알람'.

        원재료가 아닌 부품 공급사에게도 replenish_request 알림이 나가야 한다.
        """
        self._seed_forecast(onhand=60.0, incoming=0.0, daily=20.0, days=10)
        Notification = self.env["supplier.portal.notification"]
        Notification.search([("partner_id", "=", self.partner.id)]).unlink()

        self.env["supplier.supply.status"].cron_notify_replenishment()

        notif = Notification.search([
            ("partner_id", "=", self.partner.id),
            ("notification_type", "=", "replenish_request"),
        ])
        self.assertEqual(len(notif), 1)
        self.assertEqual(notif.product_id, self.product)
        self.assertEqual(notif.due_date, self.today + timedelta(days=3))
        self.assertIn("부품", notif.message)

    def test_cron_does_not_duplicate_unread_notification(self):
        """매일 도는 크론이 같은 알림을 쌓으면 벨이 무의미해진다."""
        self._seed_forecast(onhand=60.0, incoming=0.0, daily=20.0, days=10)
        Notification = self.env["supplier.portal.notification"]
        Notification.search([("partner_id", "=", self.partner.id)]).unlink()

        Status = self.env["supplier.supply.status"]
        self.assertEqual(Status.cron_notify_replenishment(), 1)
        self.assertEqual(Status.cron_notify_replenishment(), 0)
        self.assertEqual(Notification.search_count([
            ("partner_id", "=", self.partner.id),
            ("notification_type", "=", "replenish_request"),
        ]), 1)

    def test_cron_renotifies_after_read(self):
        """읽고 나서도 여전히 부족하면 다시 알려야 한다 — 한 번 읽고 끝이면 안 된다."""
        self._seed_forecast(onhand=60.0, incoming=0.0, daily=20.0, days=10)
        Notification = self.env["supplier.portal.notification"]
        Notification.search([("partner_id", "=", self.partner.id)]).unlink()
        Status = self.env["supplier.supply.status"]

        Status.cron_notify_replenishment()
        Notification.search([("partner_id", "=", self.partner.id)]).action_mark_read()
        self.assertEqual(Status.cron_notify_replenishment(), 1)

    def test_cron_is_silent_when_supply_is_healthy(self):
        self._seed_forecast(onhand=1000.0, incoming=0.0, daily=10.0, days=10)
        Notification = self.env["supplier.portal.notification"]
        Notification.search([("partner_id", "=", self.partner.id)]).unlink()
        self.env["supplier.supply.status"].cron_notify_replenishment()
        self.assertEqual(Notification.search_count([
            ("partner_id", "=", self.partner.id)]), 0)

    def test_nav_menu_inherit_is_applied(self):
        """네비 xpath 가 안 맞으면 조용히 실패해서 링크가 안 생긴다."""
        layout = self.env.ref("supplier_portal_purchase.portal_layout")
        arch = etree.tostring(layout._get_combined_arch(), encoding="unicode")
        self.assertIn("/supplier/supply-status", arch)


@tagged("post_install", "-at_install")
class TestSupplyStatusRoute(HttpCase):
    """실제 라우트로 화면을 받아본다.

    ir.qweb._render 로는 website.layout 이 main_object 를 못 찾아 죽는다 —
    그건 템플릿 결함이 아니라 렌더 방식의 문제다. 협력사가 실제로 겪는 경로는
    HTTP 요청이므로 그것으로 검증한다.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.token = "tsts" + "0123456789abcdef" * 2  # 20자 이상
        cls.partner = cls.env["res.partner"].create({
            "name": "TEST-라우트공급사",
            "is_supplier_portal": True,
            "supplier_portal_token": cls.token,
        })
        cls.product = cls.env["product.product"].create({
            "name": "TEST-라우트-부품",
            "type": "consu",
            "is_storable": True,
        })

    def _seed(self, onhand, daily, days=10):
        today = fields.Date.context_today(self.partner)
        cum = 0.0
        rows = []
        for i in range(days):
            cum += daily
            rows.append({
                "partner_id": self.partner.id,
                "product_id": self.product.id,
                "date": today + timedelta(days=i),
                "qty_required": daily,
                "cum_required": cum,
                "qty_onhand": onhand,
                "qty_incoming": 0.0,
                "qty_shortfall": max(0.0, cum - onhand),
                "snapshot_at": fields.Datetime.now(),
            })
        self.env["supplier.demand.forecast"].create(rows)
        self.env.flush_all()

    def test_route_renders_chart(self):
        self._seed(onhand=60.0, daily=20.0)
        resp = self.url_open("/supplier/supply-status?token=%s" % self.token)
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn("<svg", html)
        self.assertIn("polyline", html)
        self.assertIn("TEST-라우트-부품", html)
        # 네비 링크가 실제 렌더 결과에 있어야 협력사가 이 화면에 들어올 수 있다
        self.assertIn("/supplier/supply-status?token=", html)

    def test_route_renders_when_empty(self):
        """전망이 아직 없는 신규 협력사에서 화면이 깨지면 안 된다."""
        resp = self.url_open("/supplier/supply-status?token=%s" % self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Internal Server Error", resp.text)

    def test_route_rejects_bad_token(self):
        """토큰 없이 남의 재고·생산계획이 보이면 안 된다."""
        resp = self.url_open("/supplier/supply-status?token=nope")
        self.assertEqual(resp.status_code, 200)  # 거부 화면도 200 으로 렌더된다
        self.assertNotIn("<svg", resp.text)
