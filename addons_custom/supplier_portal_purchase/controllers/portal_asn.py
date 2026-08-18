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
