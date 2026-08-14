from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .portal import SupplierPortalController


class SupplierPortalReceiptController(http.Controller):
    """협력사 포털 — 납품 인수증(입고 전표 기반 인수확인서 PDF)."""

    def _validate(self, token):
        # 기존 포털 토큰 검증(만료·위조 차단) 재사용
        return SupplierPortalController()._validate_portal_access(token)

    def _partner_receipts(self, partner):
        return request.env["stock.picking"].sudo().search([
            ("partner_id", "=", partner.id),
            ("picking_type_code", "=", "incoming"),
            ("state", "=", "done"),
        ], order="date_done desc", limit=100)

    @http.route("/supplier/receipts", type="http", auth="public", website=True)
    def receipts(self, token=None, **kwargs):
        try:
            partner = self._validate(token)
        except AccessDenied as e:
            return request.render(
                "supplier_portal_purchase.portal_access_denied", {"error": str(e)})
        return request.render("supplier_portal_purchase.portal_receipts", {
            "partner": partner,
            "token": token,
            "pickings": self._partner_receipts(partner),
            "page_name": "receipts",
        })

    @http.route("/supplier/receipt/<int:picking_id>/pdf",
                type="http", auth="public", website=True)
    def receipt_pdf(self, picking_id, token=None, **kwargs):
        try:
            partner = self._validate(token)
        except AccessDenied as e:
            return request.render(
                "supplier_portal_purchase.portal_access_denied", {"error": str(e)})
        picking = request.env["stock.picking"].sudo().browse(picking_id).exists()
        # 소유 검증: 본인(협력사) 납품의 완료된 입고 전표만
        if (not picking or picking.partner_id != partner
                or picking.picking_type_code != "incoming"
                or picking.state != "done"):
            return request.render(
                "supplier_portal_purchase.portal_access_denied",
                {"error": "해당 인수증에 접근할 수 없습니다."})
        pdf, _type = request.env["ir.actions.report"].sudo()._render_qweb_pdf(
            "supplier_portal_purchase.action_report_supplier_receipt", [picking.id])
        filename = "인수확인서-%s.pdf" % picking.name.replace("/", "-")
        return request.make_response(pdf, headers=[
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(pdf)),
            ("Content-Disposition", http.content_disposition(filename)),
        ])
