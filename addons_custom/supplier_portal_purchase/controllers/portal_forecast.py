from collections import defaultdict

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .portal import SupplierPortalController


class SupplierPortalForecastController(http.Controller):
    """협력사 포탈 — 소요 전망(비구속) 조회."""

    @http.route("/supplier/forecast", type="http", auth="public", website=True)
    def forecast(self, token=None, **kwargs):
        try:
            partner = SupplierPortalController()._validate_portal_access(token)
        except AccessDenied as e:
            return request.render(
                "supplier_portal_purchase.portal_access_denied", {"error": str(e)})
        lines = request.env["supplier.demand.forecast"].sudo().search(
            [("partner_id", "=", partner.id)], order="product_id, date")
        by_product = defaultdict(list)
        for line in lines:
            by_product[line.product_id].append(line)
        snapshot_at = lines[:1].snapshot_at if lines else False
        return request.render("supplier_portal_purchase.portal_forecast", {
            "partner": partner, "token": token,
            "by_product": by_product, "snapshot_at": snapshot_at,
            "page_name": "forecast",
        })
