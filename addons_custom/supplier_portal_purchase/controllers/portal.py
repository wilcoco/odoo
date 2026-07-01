import json
from datetime import datetime

from odoo import http, fields, _
from odoo.http import request
from odoo.exceptions import AccessDenied, ValidationError


def _to_int(value, default=0):
    """폼 입력을 안전하게 정수로 변환 (빈 값/오류 시 default)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    """폼 입력을 안전하게 실수로 변환 (빈 값/오류 시 default)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class SupplierPortalController(http.Controller):
    """협력사 포탈 컨트롤러"""

    def _validate_portal_access(self, token):
        """토큰 검증 및 협력사 반환"""
        # 예측가능/약한 토큰 방어: 빈 값·데모 토큰·짧은 토큰은 즉시 거부.
        if not token or token.startswith("demo_token_") or len(token) < 20:
            raise AccessDenied(_("접근 토큰이 필요합니다."))

        partner = request.env["res.partner"].sudo().search([
            ("supplier_portal_token", "=", token),
            ("supplier_portal_token", "!=", False),
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
                confirmed_qty = _to_float(post.get(f"qty_{line.id}"), line.product_qty)
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

    # ─────────────────────────────────────────────
    # 공급망 현황
    # ─────────────────────────────────────────────
    @http.route("/supplier/supply-chain", type="http", auth="public", website=True)
    def supply_chain_status(self, token=None, filter="active", **kwargs):
        """공급망 현황"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Status = request.env["supply.chain.order.status"].sudo()

        # 내가 담당하는 공급망 상태 조회
        domain = [("supplier_id", "=", partner.id)]

        if filter == "active":
            domain.append(("state", "not in", ["completed", "issue"]))
        elif filter == "completed":
            domain.append(("state", "=", "completed"))

        all_statuses = Status.search(domain, order="expected_date asc")

        # 처리 필요 건 (알림받음, 확정, 출하 상태)
        pending_actions = Status.search([
            ("supplier_id", "=", partner.id),
            ("state", "in", ["notified", "confirmed", "shipped"]),
        ], order="expected_date asc")

        return request.render("supplier_portal_purchase.portal_supply_chain", {
            "partner": partner,
            "token": token,
            "filter": filter,
            "all_statuses": all_statuses,
            "pending_actions": pending_actions,
        })

    @http.route("/supplier/supply-chain/<int:status_id>/confirm", type="http",
                auth="public", website=True, methods=["POST"])
    def supply_chain_confirm(self, status_id, token=None, **kwargs):
        """공급망 단계 확정"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Status = request.env["supply.chain.order.status"].sudo()
        status = Status.browse(status_id)

        if status.exists() and status.supplier_id.id == partner.id:
            status.action_confirm()

        return request.redirect(f"/supplier/supply-chain?token={token}")

    @http.route("/supplier/supply-chain/<int:status_id>/ship", type="http",
                auth="public", website=True, methods=["POST"])
    def supply_chain_ship(self, status_id, token=None, **kwargs):
        """공급망 단계 출하"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Status = request.env["supply.chain.order.status"].sudo()
        status = Status.browse(status_id)

        if status.exists() and status.supplier_id.id == partner.id:
            status.action_ship()
            # 다음 단계에 알림 (있으면)
            if status.next_tier_id:
                next_status = Status.search([
                    ("chain_order_id", "=", status.chain_order_id.id),
                    ("tier_id", "=", status.next_tier_id.id),
                ], limit=1)
                if next_status and next_status.state == "pending":
                    next_status.action_notify()

        return request.redirect(f"/supplier/supply-chain?token={token}")

    @http.route("/supplier/supply-chain/<int:status_id>/complete", type="http",
                auth="public", website=True, methods=["POST"])
    def supply_chain_complete(self, status_id, token=None, **kwargs):
        """공급망 단계 완료"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Status = request.env["supply.chain.order.status"].sudo()
        status = Status.browse(status_id)

        if status.exists() and status.supplier_id.id == partner.id:
            status.action_complete()

        return request.redirect(f"/supplier/supply-chain?token={token}")

    @http.route("/supplier/supply-chain/<int:status_id>/issue", type="http",
                auth="public", website=True)
    def supply_chain_issue_form(self, status_id, token=None, **kwargs):
        """공급망 이슈 보고 폼"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Status = request.env["supply.chain.order.status"].sudo()
        status = Status.browse(status_id)

        if not status.exists() or status.supplier_id.id != partner.id:
            return request.redirect(f"/supplier/supply-chain?token={token}")

        return request.render("supplier_portal_purchase.portal_supply_chain_issue", {
            "partner": partner,
            "token": token,
            "status": status,
        })

    @http.route("/supplier/supply-chain/<int:status_id>/issue/submit", type="http",
                auth="public", website=True, methods=["POST"], csrf=False)
    def supply_chain_issue_submit(self, status_id, token=None, **post):
        """공급망 이슈 보고 제출"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Status = request.env["supply.chain.order.status"].sudo()
        status = Status.browse(status_id)

        if status.exists() and status.supplier_id.id == partner.id:
            status.write({
                "state": "issue",
                "issue_note": post.get("issue_note", ""),
            })
            status.action_report_issue()

        return request.redirect(f"/supplier/supply-chain?token={token}")

    # ─────────────────────────────────────────────
    # 재고 현황
    # ─────────────────────────────────────────────
    @http.route("/supplier/inventory", type="http", auth="public", website=True)
    def inventory_status(self, token=None, **kwargs):
        """재고 현황 (협력사 관점)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        # 협력사가 납품하는 제품 목록
        Product = request.env["product.product"].sudo()
        products = Product.search([
            ("is_outsourced", "=", True),
            ("outsource_partner_id", "=", partner.id),
        ])

        # 공급망에서 내가 담당하는 제품
        Status = request.env["supply.chain.order.status"].sudo()
        chain_statuses = Status.search([
            ("supplier_id", "=", partner.id),
            ("state", "not in", ["completed", "issue"]),
        ])
        chain_products = chain_statuses.mapped("chain_order_id.product_id")
        products |= chain_products

        # 재고 정보 집계
        inventory_items = []
        incoming_count = 0
        outgoing_count = 0

        for product in products:
            # 입고 예정 (상위 업체에서 나에게)
            incoming = Status.search_count([
                ("next_supplier_id", "=", partner.id),
                ("chain_order_id.product_id", "=", product.id),
                ("state", "in", ["confirmed", "shipped"]),
            ])

            # 출고 예정 (내가 하위로)
            outgoing = Status.search_count([
                ("supplier_id", "=", partner.id),
                ("chain_order_id.product_id", "=", product.id),
                ("state", "in", ["notified", "confirmed"]),
            ])

            incoming_count += incoming
            outgoing_count += outgoing

            inventory_items.append({
                "code": product.default_code or "-",
                "name": product.name,
                "qty_on_hand": 0,  # 협력사 재고는 Odoo에서 관리 안함
                "incoming": incoming,
                "outgoing": outgoing,
                "available": incoming - outgoing,
            })

        inventory_summary = {
            "total_products": len(products),
            "incoming_count": incoming_count,
            "outgoing_count": outgoing_count,
        }

        return request.render("supplier_portal_purchase.portal_inventory", {
            "partner": partner,
            "token": token,
            "inventory_items": inventory_items,
            "inventory_summary": inventory_summary,
        })

    # ─────────────────────────────────────────────
    # 협력사 간 발주 (발주 관리 - 내가 발주한 것)
    # ─────────────────────────────────────────────
    @http.route("/supplier/orders", type="http", auth="public", website=True)
    def my_orders(self, token=None, state=None, page=1, **kwargs):
        """내가 발주한 주문 목록 (발주 관리)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()

        domain = [("buyer_partner_id", "=", partner.id)]
        if state and state != "all":
            domain.append(("state", "=", state))

        page = int(page)
        per_page = 10
        total = Order.search_count(domain)
        offset = (page - 1) * per_page

        orders = Order.search(
            domain,
            order="create_date desc",
            limit=per_page,
            offset=offset,
        )

        return request.render("supplier_portal_purchase.portal_my_orders", {
            "partner": partner,
            "token": token,
            "orders": orders,
            "state_filter": state or "all",
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        })

    @http.route("/supplier/orders/new", type="http", auth="public", website=True)
    def new_order_form(self, token=None, **kwargs):
        """새 발주 작성 폼"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        # 발주 가능한 공급업체 목록
        suppliers = request.env["res.partner"].sudo().search([
            ("is_supplier_portal", "=", True),
            ("id", "!=", partner.id),
        ])

        # 제품 목록
        products = request.env["product.product"].sudo().search([
            ("is_outsourced", "=", True),
        ])

        return request.render("supplier_portal_purchase.portal_new_order", {
            "partner": partner,
            "token": token,
            "suppliers": suppliers,
            "products": products,
        })

    @http.route("/supplier/orders/create", type="http", auth="public",
                website=True, methods=["POST"], csrf=False)
    def create_order(self, token=None, **post):
        """새 발주 생성"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()

        seller_id = _to_int(post.get("seller_id"))
        product_id = _to_int(post.get("product_id"))
        quantity = _to_float(post.get("quantity"))
        date_required = post.get("date_required")

        if not all([seller_id, product_id, quantity, date_required]):
            return request.redirect(f"/supplier/orders/new?token={token}&error=missing_fields")

        # 스푸핑 방지: 판매자·품목이 폼 허용집합(new_order_form)에 속하는지 서버측 재검증.
        seller = request.env["res.partner"].sudo().browse(seller_id)
        if not seller.exists() or not seller.is_supplier_portal or seller.id == partner.id:
            return request.redirect(f"/supplier/orders/new?token={token}&error=invalid_seller")
        product = request.env["product.product"].sudo().browse(product_id)
        if not product.exists() or not product.is_outsourced:
            return request.redirect(f"/supplier/orders/new?token={token}&error=invalid_product")

        order = Order.create({
            "buyer_partner_id": partner.id,
            "seller_partner_id": seller_id,
            "product_id": product_id,
            "quantity": quantity,
            "date_required": date_required,
            "notes": post.get("notes", ""),
        })

        # 자동 전송
        order.action_send()

        return request.redirect(f"/supplier/orders?token={token}&success=1")

    @http.route("/supplier/orders/<int:order_id>", type="http", auth="public", website=True)
    def order_detail(self, order_id, token=None, **kwargs):
        """발주 상세 (내가 발주한 것)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()
        order = Order.browse(order_id)

        if not order.exists() or order.buyer_partner_id.id != partner.id:
            return request.redirect(f"/supplier/orders?token={token}&error=access_denied")

        return request.render("supplier_portal_purchase.portal_order_detail", {
            "partner": partner,
            "token": token,
            "order": order,
            "is_buyer": True,
        })

    @http.route("/supplier/orders/<int:order_id>/receive", type="http",
                auth="public", website=True, methods=["POST"])
    def order_receive(self, order_id, token=None, **kwargs):
        """입고 확인 (발주자)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()
        order = Order.browse(order_id)

        if order.exists() and order.buyer_partner_id.id == partner.id:
            order.action_receive()

        return request.redirect(f"/supplier/orders/{order_id}?token={token}")

    # ─────────────────────────────────────────────
    # 협력사 간 수주 (수주 관리 - 내가 받은 발주)
    # ─────────────────────────────────────────────
    @http.route("/supplier/incoming-orders", type="http", auth="public", website=True)
    def incoming_orders(self, token=None, state=None, page=1, **kwargs):
        """내가 받은 발주 목록 (수주 관리)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()

        domain = [("seller_partner_id", "=", partner.id)]
        if state and state != "all":
            domain.append(("state", "=", state))

        page = int(page)
        per_page = 10
        total = Order.search_count(domain)
        offset = (page - 1) * per_page

        orders = Order.search(
            domain,
            order="create_date desc",
            limit=per_page,
            offset=offset,
        )

        return request.render("supplier_portal_purchase.portal_incoming_orders", {
            "partner": partner,
            "token": token,
            "orders": orders,
            "state_filter": state or "all",
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page,
        })

    @http.route("/supplier/incoming-orders/<int:order_id>", type="http",
                auth="public", website=True)
    def incoming_order_detail(self, order_id, token=None, **kwargs):
        """수주 상세 (내가 받은 발주)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()
        order = Order.browse(order_id)

        if not order.exists() or order.seller_partner_id.id != partner.id:
            return request.redirect(f"/supplier/incoming-orders?token={token}&error=access_denied")

        return request.render("supplier_portal_purchase.portal_order_detail", {
            "partner": partner,
            "token": token,
            "order": order,
            "is_buyer": False,
        })

    @http.route("/supplier/incoming-orders/<int:order_id>/confirm", type="http",
                auth="public", website=True, methods=["POST"])
    def incoming_order_confirm(self, order_id, token=None, **kwargs):
        """수주 확정 (공급자)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()
        order = Order.browse(order_id)

        if order.exists() and order.seller_partner_id.id == partner.id:
            order.action_confirm()

        return request.redirect(f"/supplier/incoming-orders/{order_id}?token={token}")

    @http.route("/supplier/incoming-orders/<int:order_id>/ship", type="http",
                auth="public", website=True, methods=["POST"])
    def incoming_order_ship(self, order_id, token=None, **kwargs):
        """출하 처리 (공급자)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()
        order = Order.browse(order_id)

        if order.exists() and order.seller_partner_id.id == partner.id:
            order.action_ship()

        return request.redirect(f"/supplier/incoming-orders/{order_id}?token={token}")

    # ─────────────────────────────────────────────
    # 입고 현황 (내가 발주한 것의 입고)
    # ─────────────────────────────────────────────
    @http.route("/supplier/receiving", type="http", auth="public", website=True)
    def receiving_status(self, token=None, **kwargs):
        """입고 현황 (내가 발주한 건의 입고 상태)"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Order = request.env["supplier.order"].sudo()

        # 입고 대기 (출하완료, 아직 입고 안됨)
        pending = Order.search([
            ("buyer_partner_id", "=", partner.id),
            ("state", "=", "shipped"),
        ], order="date_required asc")

        # 입고 예정 (확정됨, 아직 출하 안됨)
        upcoming = Order.search([
            ("buyer_partner_id", "=", partner.id),
            ("state", "=", "confirmed"),
        ], order="date_required asc")

        # 최근 입고 완료 (30일)
        thirty_days_ago = fields.Date.subtract(fields.Date.today(), days=30)
        completed = Order.search([
            ("buyer_partner_id", "=", partner.id),
            ("state", "=", "received"),
            ("date_received", ">=", thirty_days_ago),
        ], order="date_received desc", limit=20)

        return request.render("supplier_portal_purchase.portal_receiving", {
            "partner": partner,
            "token": token,
            "pending": pending,
            "upcoming": upcoming,
            "completed": completed,
        })

    # ─────────────────────────────────────────────
    # 협력사 자체 재고 관리
    # ─────────────────────────────────────────────
    @http.route("/supplier/my-inventory", type="http", auth="public", website=True)
    def my_inventory(self, token=None, **kwargs):
        """내 재고 현황"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Inventory = request.env["supplier.inventory"].sudo()
        inventory_items = Inventory.search([
            ("partner_id", "=", partner.id),
        ])

        return request.render("supplier_portal_purchase.portal_my_inventory", {
            "partner": partner,
            "token": token,
            "inventory_items": inventory_items,
        })

    @http.route("/supplier/my-inventory/update", type="http", auth="public",
                website=True, methods=["POST"], csrf=False)
    def update_my_inventory(self, token=None, **post):
        """재고 수량 업데이트"""
        try:
            partner = self._validate_portal_access(token)
        except AccessDenied as e:
            return request.render("supplier_portal_purchase.portal_access_denied", {
                "error": str(e),
            })

        Inventory = request.env["supplier.inventory"].sudo()

        product_id = _to_int(post.get("product_id"))
        quantity = _to_float(post.get("quantity"))

        if product_id:
            inv = Inventory.search([
                ("partner_id", "=", partner.id),
                ("product_id", "=", product_id),
            ], limit=1)

            if inv:
                inv.write({
                    "quantity": quantity,
                    "last_updated": fields.Datetime.now(),
                })
            else:
                Inventory.create({
                    "partner_id": partner.id,
                    "product_id": product_id,
                    "quantity": quantity,
                })

        return request.redirect(f"/supplier/my-inventory?token={token}")
