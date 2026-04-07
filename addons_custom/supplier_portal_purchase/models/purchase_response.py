from odoo import api, fields, models, _


class PurchaseOrderResponse(models.Model):
    """협력사 응답 (정형화)"""
    _name = "purchase.order.response"
    _description = "협력사 발주 응답"
    _order = "create_date desc"

    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="발주서",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(
        related="purchase_order_id.partner_id",
        store=True,
    )
    response_type = fields.Selection(
        [
            ("full_accept", "전체 승인"),
            ("partial_accept", "조건부 승인"),
            ("reject", "납품 불가"),
        ],
        string="응답 유형",
        required=True,
    )
    response_date = fields.Datetime(
        string="응답 일시",
        default=fields.Datetime.now,
    )
    note = fields.Text(
        string="비고",
    )
    line_response_ids = fields.One2many(
        "purchase.order.line.response",
        "response_id",
        string="품목별 응답",
    )

    # 구매담당 검토
    review_state = fields.Selection(
        [
            ("pending", "검토 대기"),
            ("approved", "승인"),
            ("rejected", "반려"),
        ],
        string="검토 상태",
        default="pending",
    )
    reviewed_by = fields.Many2one(
        "res.users",
        string="검토자",
    )
    reviewed_date = fields.Datetime(
        string="검토 일시",
    )
    reject_reason = fields.Text(
        string="반려 사유",
    )

    @api.model_create_multi
    def create(self, vals_list):
        responses = super().create(vals_list)
        for response in responses:
            # PO 상태 변경
            response.purchase_order_id.portal_state = "responded"
            # 구매담당자에게 알림
            response.purchase_order_id._create_portal_notification(
                "response_received",
                user=response.purchase_order_id.buyer_id,
            )
        return responses


class PurchaseOrderLineResponse(models.Model):
    """품목별 응답 상세"""
    _name = "purchase.order.line.response"
    _description = "품목별 발주 응답"

    response_id = fields.Many2one(
        "purchase.order.response",
        string="응답",
        required=True,
        ondelete="cascade",
    )
    order_line_id = fields.Many2one(
        "purchase.order.line",
        string="발주 라인",
        required=True,
    )
    product_id = fields.Many2one(
        related="order_line_id.product_id",
        store=True,
    )

    # 요청 (원본)
    requested_qty = fields.Float(
        string="요청 수량",
        related="order_line_id.product_qty",
    )
    requested_date = fields.Date(
        string="요청 납기",
        related="order_line_id.date_planned",
    )

    # 협력사 응답
    confirmed_qty = fields.Float(
        string="확정 수량",
    )
    confirmed_date = fields.Date(
        string="확정 납기",
    )
    line_note = fields.Text(
        string="품목 비고",
    )
    line_status = fields.Selection(
        [
            ("ok", "일치"),
            ("qty_diff", "수량 차이"),
            ("date_diff", "납기 차이"),
            ("both_diff", "수량+납기 차이"),
            ("reject", "불가"),
        ],
        string="상태",
        compute="_compute_line_status",
        store=True,
    )

    # 구매담당 결정
    is_approved = fields.Boolean(
        string="승인",
        default=True,
    )

    @api.depends("requested_qty", "confirmed_qty", "requested_date", "confirmed_date")
    def _compute_line_status(self):
        for line in self:
            if line.confirmed_qty == 0 and not line.confirmed_date:
                line.line_status = "reject"
            elif not line.confirmed_qty or not line.confirmed_date:
                line.line_status = "ok"
            else:
                qty_diff = abs(line.requested_qty - line.confirmed_qty) > 0.01
                date_diff = line.requested_date and line.confirmed_date and \
                            line.requested_date != line.confirmed_date

                if qty_diff and date_diff:
                    line.line_status = "both_diff"
                elif qty_diff:
                    line.line_status = "qty_diff"
                elif date_diff:
                    line.line_status = "date_diff"
                else:
                    line.line_status = "ok"
