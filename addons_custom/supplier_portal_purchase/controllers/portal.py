import json
from datetime import datetime

from odoo import http, fields, _
from odoo.http import request
from odoo.exceptions import AccessDenied, ValidationError


class SupplierPortalController(http.Controller):
    """협력사 포탈 컨트롤러"""

    def _validate_portal_access(self, token):
        """토큰 검증 및 협력사 반환"""
        if not token:
            raise AccessDenied(_("접근 토큰이 필요합니다."))

        partner = request.env["res.partner"].sudo().search([
            ("supplier_portal_token", "=", token),
            ("is_supplier_portal", "=", True),
        ], limit=1)

        if not partner:
            raise AccessDenied(_("유효하지 않은 접근 토큰입니다."))

        return partner

    def _validate_po_access(self, po_id, token):
        """PO 접근 권한 검증"""
        partner = self._validate_portal_access(token)

        po = request.env["purchase.order"].sudo().browse(int(po_id))
        if not po.exists():
            raise AccessDenied(_("발주서를 찾을 수 없습니다."))

        if po.partner_id.id != partner.id:
            raise AccessDenied(_("이 발주서에 대한 접근 권한이 없습니다."))

        return partner, po

    # ─────────────────────────────────────────────
    # 대시보드
    # ─────────────────────────────────────────────
    @http.route("/supplier/portal", type="http", auth="public", website=True)
    def portal_dashboard(self, token=None, **kwargs):
        """협력사 포탈 대시보드"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        PO = request.env["purchase.order"].sudo()
        Notification = request.env["supplier.portal.notification"].sudo()

        # 발주 현황 통계
        po_stats = {
            "new": PO.search_count([
                ("partner_id", "=", partner.id),
                ("portal_state", "=", "new"),
            ]),
            "responded": PO.search_count([
                ("partner_id", "=", partner.id),
                ("portal_state", "=", "responded"),
            ]),
            "approved": PO.search_count([
                ("partner_id", "=", partner.id),
                ("portal_state", "=", "approved"),
            ]),
            "rejected": PO.search_count([
                ("partner_id", "=", partner.id),
                ("portal_state", "=", "rejected"),
            ]),
            "done": PO.search_count([
                ("partner_id", "=", partner.id),
                ("portal_state", "=", "done"),
            ]),
        }

        # 알림 목록
        notifications = Notification.get_notifications_for_partner(partner.id, limit=5)
        unread_count = Notification.get_unread_count_for_partner(partner.id)

        # 금주 납품 일정
        today = fields.Date.today()
        week_later = fields.Date.add(today, days=7)
        upcoming_pos = PO.search([
            ("partner_id", "=", partner.id),
            ("portal_state", "in", ["approved", "responded"]),
            ("date_planned", ">=", today),
            ("date_planned", "<=", week_later),
        ], order="date_planned asc", limit=5)

        return request.render("supplier_portal_purchase.portal_dashboard", {
            "partner": partner,
            "token": token,
            "po_stats": po_stats,
            "notifications": notifications,
            "unread_count": unread_count,
            "upcoming_pos": upcoming_pos,
        })

    # ─────────────────────────────────────────────
    # 발주 목록
    # ─────────────────────────────────────────────
    @http.route("/supplier/po/list", type="http", auth="public", website=True)
    def po_list(self, token=None, state=None, page=1, **kwargs):
        """발주 목록"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        PO = request.env["purchase.order"].sudo()

        domain = [
            ("partner_id", "=", partner.id),
            ("auto_generated", "=", True),
        ]

        if state and state != "all":
            domain.append(("portal_state", "=", state))

        # 페이징
        page = int(page)
        per_page = 10
        total = PO.search_count(domain)
        offset = (page - 1) * per_page

        orders = PO.search(
            domain,
            order="create_date desc",
            limit=per_page,
            offset=offset,
        )

        return request.render("supplier_portal_purchase.portal_po_list", {
            "partner": partner,
            "token": token,
            "orders": orders,
            "state_filter": state or "all",
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        })

    # ─────────────────────────────────────────────
    # 발주 상세
    # ─────────────────────────────────────────────
    @http.route("/supplier/po/<int:po_id>", type="http", auth="public", website=True)
    def po_detail(self, po_id, token=None, **kwargs):
        """발주 상세"""
        try:
            partner, po = self._validate_po_access(po_id, token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        # 반려 사유 (있을 경우)
        reject_reason = None
        if po.portal_state == "rejected" and po.latest_response_id:
            reject_reason = po.latest_response_id.reject_reason

        return request.render("supplier_portal_purchase.portal_po_detail", {
            "partner": partner,
            "token": token,
            "order": po,
            "reject_reason": reject_reason,
            "can_respond": po.portal_state in ("new", "rejected"),
        })

    # ─────────────────────────────────────────────
    # 응답 제출
    # ─────────────────────────────────────────────
    @http.route("/supplier/po/<int:po_id>/respond", type="http", auth="public",
                website=True, methods=["POST"], csrf=False)
    def po_respond(self, po_id, token=None, **post):
        """발주 응답 제출"""
        try:
            partner, po = self._validate_po_access(po_id, token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        if po.portal_state not in ("new", "rejected"):
            return request.redirect(f"/supplier/po/{po_id}?token={token}&error=invalid_state")

        # 응답 유형
        response_type = post.get("response_type", "full_accept")
        note = post.get("note", "")

        # 응답 생성
        Response = request.env["purchase.order.response"].sudo()
        LineResponse = request.env["purchase.order.line.response"].sudo()

        response = Response.create({
            "purchase_order_id": po.id,
            "response_type": response_type,
            "note": note,
        })

        # 품목별 응답 생성
        for line in po.order_line:
            if response_type == "full_accept":
                # 전체 승인: 요청대로
                confirmed_qty = line.product_qty
                confirmed_date = line.date_planned.date() if line.date_planned else fields.Date.today()
            elif response_type == "reject":
                # 납품 불가
                confirmed_qty = 0
                confirmed_date = None
            else:
                # 조건부 승인: 폼에서 입력받은 값
                confirmed_qty = float(post.get(f"qty_{line.id}", line.product_qty))
                date_str = post.get(f"date_{line.id}")
                if date_str:
                    confirmed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                else:
                    confirmed_date = line.date_planned.date() if line.date_planned else fields.Date.today()

            LineResponse.create({
                "response_id": response.id,
                "order_line_id": line.id,
                "confirmed_qty": confirmed_qty,
                "confirmed_date": confirmed_date,
                "line_note": post.get(f"note_{line.id}", ""),
            })

        return request.redirect(f"/supplier/po/{po_id}?token={token}&success=1")

    # ─────────────────────────────────────────────
    # 알림 처리
    # ─────────────────────────────────────────────
    @http.route("/supplier/notification/read", type="json", auth="public")
    def mark_notification_read(self, token=None, notification_id=None, **kwargs):
        """알림 읽음 처리"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied:
            return {"success": False, "error": "access_denied"}

        if notification_id:
            notification = request.env["supplier.portal.notification"].sudo().browse(
                int(notification_id)
            )
            if notification.exists() and notification.partner_id.id == partner.id:
                notification.action_mark_read()

        return {"success": True}

    @http.route("/supplier/notification/read_all", type="json", auth="public")
    def mark_all_notifications_read(self, token=None, **kwargs):
        """모든 알림 읽음 처리"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied:
            return {"success": False, "error": "access_denied"}

        notifications = request.env["supplier.portal.notification"].sudo().search([
            ("partner_id", "=", partner.id),
            ("is_read", "=", False),
        ])
        notifications.action_mark_read()

        return {"success": True}

    # ─────────────────────────────────────────────
    # 납품 현황
    # ─────────────────────────────────────────────
    @http.route("/supplier/delivery", type="http", auth="public", website=True)
    def delivery_status(self, token=None, **kwargs):
        """납품 현황"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        PO = request.env["purchase.order"].sudo()

        # 납품 예정
        upcoming = PO.search([
            ("partner_id", "=", partner.id),
            ("portal_state", "=", "approved"),
        ], order="date_planned asc")

        # 납품 완료 (최근 30일)
        thirty_days_ago = fields.Date.subtract(fields.Date.today(), days=30)
        completed = PO.search([
            ("partner_id", "=", partner.id),
            ("portal_state", "=", "done"),
            ("date_planned", ">=", thirty_days_ago),
        ], order="date_planned desc", limit=20)

        return request.render("supplier_portal_purchase.portal_delivery", {
            "partner": partner,
            "token": token,
            "upcoming": upcoming,
            "completed": completed,
        })
