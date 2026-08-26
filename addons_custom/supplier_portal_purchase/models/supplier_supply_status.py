"""협력사 포탈 — 공급 현황(그래픽) 데이터 구성.

왜 하나의 모델인가:
  원재료(수지)와 부품은 **부족을 재는 자가 다를 뿐** 구조가 같다.
    · 원재료: 사일로 잔량이 재주문점(예: 9톤) 이하로 떨어지는가
    · 부품  : 누적 소요가 (보유 + 입고예정)을 넘어서는가
  둘 다 "임계선 아래로 내려가는 곡선"이다. 그래서 임계선의 값과 곡선의 출처만
  갈아끼우고, 차트·알람·화면은 하나로 공유한다.

  다른 점은 딱 하나 — 원재료는 임계 도달 시 **명시적 보충 요청**(소요예상 통보,
  material.requirement.notice)이 발행된다는 것. 부품은 통보서 없이 부족 신호만
  뜬다. 이 차이는 alert dict 의 `has_request` 플래그 하나로 표현한다.

차트는 서버에서 SVG 로 그린다. 포탈에 JS 차트 라이브러리를 새로 끌어오지 않는
이유는, 협력사 단말 환경이 제각각이고 자산 번들 실패 시 화면이 통째로 비기
때문이다. SVG 는 실패할 여지가 없고 인쇄·PDF 로도 그대로 나간다.
"""

from collections import defaultdict

from odoo import api, fields, models, _

# 차트 기하 (px)
CHART_W = 720
CHART_H = 200
PAD_L = 52
PAD_R = 12
PAD_T = 14
PAD_B = 28


class SupplierSupplyStatus(models.AbstractModel):
    _name = "supplier.supply.status"
    _description = "협력사 공급 현황(그래픽) 데이터"

    # ────────────────────────────────────────────────────────────
    # 차트 (서버 사이드 SVG 기하 계산)
    # ────────────────────────────────────────────────────────────
    @api.model
    def _build_chart(self, series, threshold=None):
        """series: [{'label','stock','required'}] → SVG 좌표 묶음.

        stock  = 꺾은선 (예상 잔량 / 예상 가용)
        required = 막대 (그날 소요)
        threshold = 수평 임계선 (원재료 재주문점, 부품은 0)
        """
        n = len(series)
        if not n:
            return False

        plot_w = CHART_W - PAD_L - PAD_R
        plot_h = CHART_H - PAD_T - PAD_B

        stocks = [s["stock"] for s in series]
        reqs = [s["required"] for s in series]
        y_hi = max(stocks + [threshold or 0.0] + [0.0])
        y_lo = min(stocks + [0.0])
        if y_hi <= y_lo:
            y_hi = y_lo + 1.0
        span = y_hi - y_lo

        def ypx(v):
            return PAD_T + plot_h - ((v - y_lo) / span) * plot_h

        step = plot_w / max(n, 1)

        points = []
        bars = []
        req_max = max(reqs) or 1.0
        for i, s in enumerate(series):
            cx = PAD_L + step * i + step / 2.0
            points.append("%.1f,%.1f" % (cx, ypx(s["stock"])))
            bar_h = (s["required"] / req_max) * (plot_h * 0.32)
            bars.append({
                "x": cx - min(step * 0.3, 9),
                "y": PAD_T + plot_h - bar_h,
                "w": min(step * 0.6, 18),
                "h": bar_h,
                "label": s["label"],
                "value": s["required"],
            })

        # x축 라벨은 최대 8개만 (촘촘하면 겹쳐서 못 읽는다)
        tick_every = max(1, n // 8)
        ticks = [{"x": PAD_L + step * i + step / 2.0, "label": s["label"]}
                 for i, s in enumerate(series) if i % tick_every == 0]

        # y축 눈금 4단
        grid = []
        for k in range(5):
            v = y_lo + span * k / 4.0
            grid.append({"y": ypx(v), "label": self._fmt_qty(v)})

        return {
            "width": CHART_W, "height": CHART_H,
            "plot_x": PAD_L, "plot_y": PAD_T,
            "plot_w": plot_w, "plot_h": plot_h,
            "points": " ".join(points),
            "area": "%.1f,%.1f " % (PAD_L, PAD_T + plot_h)
                    + " ".join(points)
                    + " %.1f,%.1f" % (PAD_L + plot_w, PAD_T + plot_h),
            "bars": bars,
            "ticks": ticks,
            "grid": grid,
            "threshold_y": ypx(threshold) if threshold is not None else False,
            "threshold_label": self._fmt_qty(threshold) if threshold is not None else "",
            "baseline_y": ypx(0.0),
        }

    @api.model
    def _fmt_qty(self, v):
        v = v or 0.0
        return "{:,.0f}".format(v) if abs(v) >= 1000 else "{:,.1f}".format(v)

    # ────────────────────────────────────────────────────────────
    # 원재료(사일로) — injection_worksite 가 설치된 경우에만
    # ────────────────────────────────────────────────────────────
    @api.model
    def _silo_available(self):
        """사출 현장 모듈은 이 모듈의 의존이 아니다 — 있으면 쓰고 없으면 건너뛴다."""
        return "injection.stock.silo" in self.env

    @api.model
    def _silo_blocks(self, partner):
        if not self._silo_available():
            return []
        Silo = self.env["injection.stock.silo"].sudo()
        # 이 협력사가 대는 원재료 사일로: 명시 지정 또는 품목 대표 공급사
        silos = Silo.search([("product_id", "!=", False)])
        mine = silos.filtered(
            lambda s: (s.reorder_partner_id
                       and s.reorder_partner_id.commercial_partner_id == partner)
            or (not s.reorder_partner_id
                and s.product_id.seller_ids[:1].partner_id.commercial_partner_id == partner))
        blocks = []
        for silo in mine:
            lines = silo.depletion_line_ids.sorted("plan_date")
            series = [{
                "label": l.plan_date.strftime("%m/%d"),
                "date": l.plan_date,
                "stock": l.qty_end,
                "required": l.qty_consumed,
                "refill": l.qty_refill,
            } for l in lines]
            blocks.append({
                "kind": "material",
                "kind_label": _("원재료 (사일로)"),
                "product": silo.product_id,
                "uom": silo.product_id.uom_id.name or "kg",
                "silo": silo,
                "onhand": silo.current_qty,
                "capacity": silo.capacity,
                "fill_percent": silo.fill_percent,
                "threshold": silo.reorder_point,
                "threshold_label": _("재주문점"),
                "series": series,
                "chart": self._build_chart(series, threshold=silo.reorder_point),
                "alert": self._silo_alert(silo, partner),
            })
        return blocks

    @api.model
    def _silo_alert(self, silo, partner):
        """원재료 알람 — 임계 이하면 '명시적 보충 요청'이 발행된다."""
        Notice = self.env["material.requirement.notice"].sudo() \
            if "material.requirement.notice" in self.env else False
        open_notice = False
        if Notice:
            open_notice = Notice.search([
                ("silo_id", "=", silo.id),
                ("partner_id", "=", partner.id),
                ("state", "in", ("draft", "sent")),
            ], order="notice_date desc", limit=1)

        status = silo.forecast_status
        if open_notice:
            return {
                "level": "danger",
                "has_request": True,
                "title": _("보충 요청 — %s") % open_notice.name,
                "qty": open_notice.expected_qty,
                "uom": open_notice.uom_id.name or "kg",
                "due_date": open_notice.expected_stockout_date or silo.empty_date,
                "detail": _("사일로 잔량이 재주문점(%(rp)s) 아래입니다. "
                            "%(qty)s%(uom)s 보충을 요청드립니다.") % {
                    "rp": self._fmt_qty(silo.reorder_point),
                    "qty": self._fmt_qty(open_notice.expected_qty),
                    "uom": open_notice.uom_id.name or "kg"},
                "notice": open_notice,
            }
        if status in ("due_now", "stockout"):
            return {
                "level": "danger", "has_request": False,
                "title": _("보충 필요"),
                "qty": silo.reorder_qty, "uom": silo.product_id.uom_id.name or "kg",
                "due_date": silo.empty_date,
                "detail": _("계획 기준 곧 재주문점에 도달합니다."),
            }
        if status == "due_soon":
            return {
                "level": "warning", "has_request": False,
                "title": _("보충 임박"),
                "qty": silo.reorder_qty, "uom": silo.product_id.uom_id.name or "kg",
                "due_date": silo.reorder_due_date,
                "detail": _("%s 경 보충 요청이 나갈 예정입니다.") % (
                    silo.reorder_due_date or "-"),
            }
        return {"level": "ok", "has_request": False, "title": _("여유"),
                "detail": _("현재 계획 기준 보충이 필요하지 않습니다."),
                "qty": 0.0, "uom": "", "due_date": silo.depletion_date}

    # ────────────────────────────────────────────────────────────
    # 부품 — supplier.demand.forecast
    # ────────────────────────────────────────────────────────────
    @api.model
    def _part_blocks(self, partner):
        Forecast = self.env["supplier.demand.forecast"].sudo()
        rows = Forecast.search([("partner_id", "=", partner.id)], order="product_id, date")
        by_product = defaultdict(list)
        for r in rows:
            by_product[r.product_id].append(r)

        blocks = []
        for product, lines in by_product.items():
            available = (lines[0].qty_onhand or 0.0) + (lines[0].qty_incoming or 0.0)
            series = [{
                "label": l.date.strftime("%m/%d"),
                "date": l.date,
                # 부품의 '잔량' = 가용 − 누적소요. 0 아래로 내려가면 부족이다.
                "stock": available - (l.cum_required or 0.0),
                "required": l.qty_required or 0.0,
                "refill": 0.0,
            } for l in lines]
            shortfall_lines = [l for l in lines if (l.qty_shortfall or 0.0) > 0]
            blocks.append({
                "kind": "part",
                "kind_label": _("부품"),
                "product": product,
                "uom": product.uom_id.name or "",
                "silo": False,
                "onhand": lines[0].qty_onhand,
                "incoming": lines[0].qty_incoming,
                "capacity": 0.0,
                "fill_percent": 0.0,
                "threshold": 0.0,
                "threshold_label": _("부족 기준선"),
                "series": series,
                "chart": self._build_chart(series, threshold=0.0),
                "alert": self._part_alert(product, shortfall_lines),
            })
        return blocks

    @api.model
    def _part_alert(self, product, shortfall_lines):
        """부품 알람 — 원재료와 같은 모양. 다만 통보서(발주 요청)는 없다."""
        if not shortfall_lines:
            return {"level": "ok", "has_request": False, "title": _("여유"),
                    "detail": _("현재 계획 기준 부족이 예상되지 않습니다."),
                    "qty": 0.0, "uom": product.uom_id.name or "", "due_date": False}
        first = shortfall_lines[0]
        last = shortfall_lines[-1]
        today = fields.Date.context_today(self)
        days = (first.date - today).days
        level = "danger" if days <= 7 else "warning"
        return {
            "level": level,
            "has_request": False,
            "title": _("납품 필요 — %s 까지") % first.date,
            "qty": last.qty_shortfall,
            "uom": product.uom_id.name or "",
            "due_date": first.date,
            "detail": _("%(d)s 부터 누적 소요가 당사 보유+입고예정을 초과합니다. "
                        "기간 말 기준 %(q)s%(u)s 추가 납품이 필요합니다.") % {
                "d": first.date, "q": self._fmt_qty(last.qty_shortfall),
                "u": product.uom_id.name or ""},
        }

    # ────────────────────────────────────────────────────────────
    # 화면 진입점
    # ────────────────────────────────────────────────────────────
    @api.model
    def get_portal_status(self, partner):
        """협력사 1곳의 공급 품목 전체 현황. 급한 것이 위로 온다."""
        blocks = self._silo_blocks(partner) + self._part_blocks(partner)
        rank = {"danger": 0, "warning": 1, "ok": 2}
        blocks.sort(key=lambda b: (rank.get(b["alert"]["level"], 3),
                                   b["product"].display_name))
        return blocks

    # ────────────────────────────────────────────────────────────
    # 알람 — 원재료·부품 구분 없이 같은 포탈 알림으로 나간다
    # ────────────────────────────────────────────────────────────
    @api.model
    def cron_notify_replenishment(self):
        """공급사별 보충 신호를 포탈 알림으로 발행.

        원재료는 별도로 소요예상 통보(material.requirement.notice)가 나가지만,
        공급사가 포탈에서 보는 **알림 벨**은 부품과 동일해야 한다. 그래야
        "원재료만 알려주고 부품은 안 알려준다"는 구멍이 생기지 않는다.

        중복 방지: 같은 (협력사, 품목)에 대해 아직 읽지 않은 보충 요청 알림이
        있으면 새로 만들지 않는다.
        """
        Notification = self.env["supplier.portal.notification"].sudo()
        partners = self.env["res.partner"].sudo().search([
            ("is_supplier_portal", "=", True),
        ])
        created = 0
        for partner in partners:
            blocks = self.get_portal_status(partner)
            for b in blocks:
                alert = b["alert"]
                if alert["level"] != "danger":
                    continue
                product = b["product"]
                existing = Notification.search([
                    ("partner_id", "=", partner.id),
                    ("product_id", "=", product.id),
                    ("notification_type", "=", "replenish_request"),
                    ("is_read", "=", False),
                ], limit=1)
                if existing:
                    continue
                Notification.create({
                    "partner_id": partner.id,
                    "product_id": product.id,
                    "notification_type": "replenish_request",
                    "due_date": alert.get("due_date") or False,
                    "message": "[%s] %s — %s" % (
                        b["kind_label"], product.display_name, alert["detail"]),
                })
                created += 1
        return created
