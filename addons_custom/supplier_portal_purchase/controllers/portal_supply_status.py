"""협력사 포탈 — 공급 현황(그래픽) 라우트.

원재료·부품을 같은 화면·같은 알람 구조로 보여준다. 자세한 설계 의도는
models/supplier_supply_status.py 상단 주석 참조.
"""

from odoo import http
from odoo.http import request
from odoo.exceptions import AccessDenied

from .portal import SupplierPortalController


class SupplierSupplyStatusPortal(SupplierPortalController):

    @http.route("/supplier/supply-status", type="http", auth="public", website=True)
    def portal_supply_status(self, token=None, **kwargs):
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied",
                                  {"error_message": str(e)})

        blocks = request.env["supplier.supply.status"].sudo().get_portal_status(partner)
        return request.render("supplier_portal_purchase.portal_supply_status", {
            "partner": partner,
            "token": token,
            "blocks": blocks,
            "urgent_count": len([b for b in blocks if b["alert"]["level"] == "danger"]),
        })
