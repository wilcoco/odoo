from odoo import api, fields, models


class SupplierPortalNotification(models.Model):
    """포탈 알림 (이메일 대신 온라인 알림)"""
    _name = "supplier.portal.notification"
    _description = "협력사 포탈 알림"
    _order = "create_date desc"

    partner_id = fields.Many2one(
        "res.partner",
        string="협력사",
        help="외부 협력사 알림용",
    )
    user_id = fields.Many2one(
        "res.users",
        string="내부 사용자",
        help="내부 사용자 알림용",
    )
    notification_type = fields.Selection(
        [
            ("new_po", "신규 발주"),
            ("confirm_request", "확정 요청"),
            ("response_received", "응답 수신"),
            ("approved", "승인"),
            ("rejected", "반려"),
            ("production_impact", "생산 영향"),
            ("delivery_done", "입고 완료"),
            ("supply_chain_notify", "공급망 알림"),
            ("supply_chain_issue", "공급망 이슈"),
            ("supplier_order_new", "협력사 발주"),
            ("supplier_order_shipped", "협력사 출하"),
            # 원재료(사일로 재주문점)와 부품(누적 부족)이 공유하는 단일 알람 유형.
            # 임계를 재는 방식만 다를 뿐 공급사가 받는 신호는 같아야 한다.
            ("replenish_request", "보충 요청"),
        ],
        string="알림 유형",
        required=True,
    )
    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="관련 발주",
    )
    product_id = fields.Many2one(
        "product.product",
        string="관련 품목",
        help="보충 요청 알림의 대상 품목",
    )
    due_date = fields.Date(
        string="기한",
        help="이 날까지 납품되지 않으면 당사 생산에 영향이 생기는 날",
    )
    message = fields.Text(
        string="메시지",
    )
    is_read = fields.Boolean(
        string="읽음",
        default=False,
    )
    read_date = fields.Datetime(
        string="읽은 시각",
    )

    def action_mark_read(self):
        """알림 읽음 처리"""
        self.write({
            "is_read": True,
            "read_date": fields.Datetime.now(),
        })
        return True

    def action_mark_all_read(self):
        """모든 알림 읽음 처리"""
        self.filtered(lambda n: not n.is_read).action_mark_read()
        return True

    @api.model
    def get_unread_count_for_partner(self, partner_id):
        """협력사의 미읽음 알림 개수"""
        return self.search_count([
            ("partner_id", "=", partner_id),
            ("is_read", "=", False),
        ])

    @api.model
    def get_unread_count_for_user(self, user_id):
        """내부 사용자의 미읽음 알림 개수"""
        return self.search_count([
            ("user_id", "=", user_id),
            ("is_read", "=", False),
        ])

    @api.model
    def get_notifications_for_partner(self, partner_id, limit=10):
        """협력사의 알림 목록"""
        notifications = self.search([
            ("partner_id", "=", partner_id),
        ], limit=limit, order="create_date desc")

        return [{
            "id": n.id,
            "type": n.notification_type,
            "message": n.message,
            "po_id": n.purchase_order_id.id,
            "po_name": n.purchase_order_id.name,
            "is_read": n.is_read,
            "create_date": n.create_date,
        } for n in notifications]
