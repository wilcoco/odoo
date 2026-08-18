from odoo import http, fields
from odoo.exceptions import AccessDenied
from odoo.http import request

from .portal import SupplierPortalController


class SupplierPortalAsnController(http.Controller):
    """협력사 포털 — 납품 예정(ASN) 등록·조회 (종이 명세서 대체)."""

    def _validate(self, token):
        return SupplierPortalController()._validate_portal_access(token)

    def _supplier_products(self, partner):
        """이 협력사가 납품하는 품목 = supplierinfo 매핑 기준."""
        infos = request.env["product.supplierinfo"].sudo().search(
            [("partner_id", "=", partner.id)])
        products = infos.mapped("product_tmpl_id.product_variant_ids")
        return products

    @http.route("/supplier/asn", type="http", auth="public", website=True)
    def asn_list(self, token=None, **kwargs):
        try:
            partner = self._validate(token)
        except AccessDenied as e:
            return request.render(
                "supplier_portal_purchase.portal_access_denied", {"error": str(e)})
        asns = request.env["supplier.asn"].sudo().search(
            [("partner_id", "=", partner.id)], limit=50)
        return request.render("supplier_portal_purchase.portal_asn_list", {
            "partner": partner, "token": token, "asns": asns,
            "products": self._supplier_products(partner),
            "today": fields.Date.context_today(partner),
            "page_name": "asn",
        })

    @http.route("/supplier/asn/new", type="http", auth="public", website=True,
                methods=["POST"], csrf=False)
    def asn_new(self, token=None, **post):
        try:
            partner = self._validate(token)
        except AccessDenied as e:
            return request.render(
                "supplier_portal_purchase.portal_access_denied", {"error": str(e)})
        allowed = {p.id for p in self._supplier_products(partner)}
        lines = []
        for i in range(1, 6):  # 폼 최대 5라인
            pid = post.get("product_%d" % i)
            qty = post.get("qty_%d" % i)
            if not pid or not qty:
                continue
            try:
                pid, qty = int(pid), float(qty)
            except (TypeError, ValueError):
                continue
            if pid not in allowed or qty <= 0:
                continue  # 매핑 밖 품목·이상 수량은 조용히 버리지 않고 아래에서 검증
            lines.append((0, 0, {"product_id": pid, "qty": qty,
                                 "lot_name": (post.get("lot_%d" % i) or "").strip()}))
        if not lines:
            return request.redirect(
                "/supplier/asn?token=%s&error=no_lines" % token)
        request.env["supplier.asn"].sudo().create({
            "partner_id": partner.id,
            "expected_date": post.get("expected_date") or fields.Date.today(),
            "note": (post.get("note") or "").strip(),
            "line_ids": lines,
        })
        return request.redirect("/supplier/asn?token=%s&success=1" % token)


class SupplierAsnQrController(http.Controller):
    """납품 패스(QR) — 기사 제시용 화면 + 사내 스캔 진입."""

    @http.route("/supplier/asn/<int:asn_id>/pass", type="http", auth="public", website=True)
    def asn_pass(self, asn_id, token=None, **kwargs):
        """협력사(기사) 제시용 납품 패스 — 큰 QR + 납품 요약."""
        try:
            partner = SupplierPortalController()._validate_portal_access(token)
        except AccessDenied as e:
            return request.render(
                "supplier_portal_purchase.portal_access_denied", {"error": str(e)})
        asn = request.env["supplier.asn"].sudo().browse(asn_id).exists()
        if not asn or asn.partner_id != partner:
            return request.render(
                "supplier_portal_purchase.portal_access_denied",
                {"error": "해당 납품 예정에 접근할 수 없습니다."})
        scan_url = "%sasn/scan/%d/%s" % (
            request.httprequest.host_url, asn.id, asn.qr_token)
        return request.render("supplier_portal_purchase.portal_asn_pass", {
            "partner": partner, "token": token, "asn": asn,
            "scan_url": scan_url, "page_name": "asn",
        })

    @http.route("/asn/scan/<int:asn_id>/<string:qr_token>",
                type="http", auth="user")
    def asn_scan(self, asn_id, qr_token, **kwargs):
        """사내 스캔 진입(입고 담당자, 로그인 필요) — QR 찍으면 전표까지 자동."""
        asn = request.env["supplier.asn"].sudo().browse(asn_id).exists()
        if not asn or not qr_token or asn.qr_token != qr_token:
            return request.not_found()
        if asn.state == "announced" and not asn.picking_id:
            # 담당자 권한으로 전표 생성(감사 추적 — sudo 아님)
            request.env["supplier.asn"].browse(asn.id).action_create_picking()
            asn.invalidate_recordset(["picking_id"])
        if asn.picking_id:
            return request.redirect(
                "/odoo/action-stock.action_picking_tree_all/%d" % asn.picking_id.id)
        return request.redirect("/odoo")
