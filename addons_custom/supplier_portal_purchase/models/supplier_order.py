import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SupplierOrder(models.Model):
    """협력사 간 발주 (공급망 내 거래)"""
    _name = "supplier.order"
    _description = "협력사 간 발주"
    _order = "create_date desc"
    _inherit = ["mail.thread"]

    name = fields.Char(
        string="발주번호",
        required=True,
        readonly=True,
        default=lambda self: _("New"),
        copy=False,
    )

    # 발주자 (구매자)
    buyer_partner_id = fields.Many2one(
        "res.partner",
        string="발주업체",
        required=True,
        domain="[('is_supplier_portal', '=', True)]",
    )

    # 공급자 (판매자)
    seller_partner_id = fields.Many2one(
        "res.partner",
        string="공급업체",
        required=True,
        domain="[('is_supplier_portal', '=', True)]",
    )

    # 공급망 추적 연결
    chain_order_id = fields.Many2one(
        "supply.chain.order",
        string="공급망 추적",
        ondelete="set null",
    )
    tier_status_id = fields.Many2one(
        "supply.chain.order.status",
        string="공급 단계",
        ondelete="set null",
    )

    # 제품/수량
    product_id = fields.Many2one(
        "product.product",
        string="제품",
        required=True,
    )
    quantity = fields.Float(
        string="수량",
        required=True,
    )
    price_unit = fields.Float(string="단가")

    # 날짜
    date_order = fields.Date(
        string="발주일",
        default=fields.Date.today,
        required=True,
    )
    date_required = fields.Date(
        string="납기일",
        required=True,
    )
    date_confirmed = fields.Date(string="확정일")
    date_shipped = fields.Date(string="출하일")
    date_received = fields.Date(string="입고일")

    # 상태
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("sent", "발주완료"),
            ("confirmed", "확정"),
            ("shipped", "출하"),
            ("received", "입고완료"),
            ("cancelled", "취소"),
        ],
        string="상태",
        default="draft",
        tracking=True,
    )

    notes = fields.Text(string="비고")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("supplier.order")
                    or _("New")
                )
        return super().create(vals_list)

    # 상태 전이 허용표 — 목표 상태: 허용 출발 상태
    _ALLOWED_TRANSITIONS = {
        "sent": ("draft",),
        "confirmed": ("sent",),
        "shipped": ("confirmed",),
        "received": ("shipped",),
        "cancelled": ("draft", "sent", "confirmed"),
    }

    def _check_transition(self, target):
        """허용되지 않은 상태 전이 차단 (포털 URL 직접 호출·중복 클릭 방어)."""
        for order in self:
            if order.state not in self._ALLOWED_TRANSITIONS[target]:
                raise UserError(_(
                    "%(name)s: '%(state)s' 상태에서는 이 처리를 할 수 없습니다.")
                    % {"name": order.name, "state": order.state})

    # ─────────────────────────────────────────────
    # 발주업체 액션 (삼성캡이 소재공업에게)
    # ─────────────────────────────────────────────
    def action_send(self):
        """발주 전송"""
        self.ensure_one()
        self._check_transition("sent")
        self.state = "sent"
        # 공급업체에게 알림
        self.env["supplier.portal.notification"].create({
            "partner_id": self.seller_partner_id.id,
            "notification_type": "supplier_order_new",
            "message": _(
                "새 발주: %s - %s x %s (납기: %s)"
            ) % (
                self.name,
                self.product_id.display_name,
                self.quantity,
                self.date_required,
            ),
        })
        return True

    # ─────────────────────────────────────────────
    # 공급업체 액션 (소재공업이 응답)
    # ─────────────────────────────────────────────
    def action_confirm(self):
        """발주 확정 (공급업체)"""
        self.ensure_one()
        self._check_transition("confirmed")
        self.state = "confirmed"
        self.date_confirmed = fields.Date.today()
        return True

    def action_ship(self):
        """출하 처리 (공급업체)"""
        self.ensure_one()
        self._check_transition("shipped")
        self.state = "shipped"
        self.date_shipped = fields.Date.today()
        # 발주업체에게 출하 알림
        self.env["supplier.portal.notification"].create({
            "partner_id": self.buyer_partner_id.id,
            "notification_type": "supplier_order_shipped",
            "message": _(
                "출하 완료: %s - %s (출하일: %s)"
            ) % (
                self.name,
                self.product_id.display_name,
                self.date_shipped,
            ),
        })
        return True

    # ─────────────────────────────────────────────
    # 발주업체 액션 (삼성캡이 입고 확인)
    # ─────────────────────────────────────────────
    def action_receive(self):
        """입고 확인 (발주업체)"""
        self.ensure_one()
        self._check_transition("received")
        self.state = "received"
        self.date_received = fields.Date.today()

        # 공급망 단계 상태 업데이트
        if self.tier_status_id:
            self.tier_status_id.action_complete()

        return True

    def action_cancel(self):
        """취소 — 출하 이후는 실물 회수가 필요하므로 취소 불가"""
        self.ensure_one()
        self._check_transition("cancelled")
        self.state = "cancelled"
        return True


class SupplierInventory(models.Model):
    """협력사 재고 (간이)"""
    _name = "supplier.inventory"
    _description = "협력사 재고"
    _order = "partner_id, product_id"

    partner_id = fields.Many2one(
        "res.partner",
        string="협력사",
        required=True,
        domain="[('is_supplier_portal', '=', True)]",
    )
    product_id = fields.Many2one(
        "product.product",
        string="제품",
        required=True,
    )
    quantity = fields.Float(
        string="재고수량",
        default=0,
    )
    last_updated = fields.Datetime(
        string="최종 수정",
        default=fields.Datetime.now,
    )

    _sql_constraints = [
        (
            "partner_product_uniq",
            "UNIQUE(partner_id, product_id)",
            "협력사별 제품 재고는 하나만 존재해야 합니다.",
        ),
    ]

    def update_quantity(self, qty_change):
        """재고 수량 변경"""
        self.quantity += qty_change
        self.last_updated = fields.Datetime.now()
