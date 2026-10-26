"""협력사 신고 재고 ↔ 납품 연동 (2026-10-19 사용자 결정).

- 협력사가 포털에서 신고한 재고는 우리 입고가 확정될 때(입고 전표 완료) 그 수량만큼 차감한다.
- 차감 뒤 신고 재고가 아직 안 들어온 요구량(확정 발주 잔량 + 무발주 소요통보 잔량)보다 적으면
  "재고 갱신 요청" 알림(포털 알림 + 메일)을 보내 협력사가 생산 후 다시 입력하게 한다.
- 이동(stock.move) 1건당 1회만 차감한다(멱등). 신고 재고가 없는 품목은 차감하지 않는다.
"""
from odoo import api, fields, models, _


class SupplierInventory(models.Model):
    _inherit = "supplier.inventory"

    outstanding_qty = fields.Float(
        string="미입고 요구량", compute="_compute_sync_state",
        help="확정 발주 잔량(+ 무발주 소요통보 잔량)으로 아직 입고되지 않은 수량. 제품 기본 단위.")
    shortage_qty = fields.Float(string="부족", compute="_compute_sync_state",
                                help="미입고 요구량 − 신고 재고. 0보다 크면 협력사가 재고를 다시 신고해야 한다.")
    needs_update = fields.Boolean(string="갱신 필요", compute="_compute_sync_state", search="_search_needs_update")
    last_deduction_date = fields.Datetime(string="최근 납품 차감", readonly=True, copy=False)
    last_deduction_qty = fields.Float(string="최근 차감 수량", readonly=True, copy=False)
    update_requested_at = fields.Datetime(string="갱신 요청 발송", readonly=True, copy=False)
    portal_inventory_url = fields.Char(string="포털 재고 화면", compute="_compute_portal_inventory_url")

    @api.depends("partner_id")
    def _compute_portal_inventory_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        for rec in self:
            token = rec.partner_id.sudo().supplier_portal_token
            rec.portal_inventory_url = "%s/supplier/my-inventory%s" % (base, ("?token=" + token) if token else "")

    def _outstanding_quantity(self):
        """우리 쪽 미입고 요구량(제품 기본 단위). 기본은 확정 발주 잔량 — 무발주 통보는 scm_no_po_supply 가 더한다."""
        self.ensure_one()
        commercial = self.partner_id.commercial_partner_id
        lines = self.env["purchase.order.line"].sudo().search([
            ("order_id.partner_id.commercial_partner_id", "=", commercial.id),
            ("order_id.state", "in", ("purchase", "done")),
            ("order_id.company_id", "=", self.company_id.id),
            ("product_id", "=", self.product_id.id),
            ("display_type", "=", False),
        ])
        total = 0.0
        for line in lines:
            remaining = max(0.0, line.product_qty - line.qty_received)
            if remaining:
                total += line.product_uom._compute_quantity(remaining, self.product_id.uom_id, round=False)
        return total

    @api.depends("quantity", "partner_id", "product_id", "company_id")
    def _compute_sync_state(self):
        for rec in self:
            outstanding = rec._outstanding_quantity() if rec.partner_id and rec.product_id and rec.company_id else 0.0
            rec.outstanding_qty = outstanding
            rec.shortage_qty = max(0.0, outstanding - rec.quantity)
            rec.needs_update = rec.shortage_qty > 0

    def _search_needs_update(self, operator, value):
        if operator not in ("=", "!="):
            return [("id", "in", [])]
        wanted = bool(value) if operator == "=" else not bool(value)
        rows = self.search([]).filtered(lambda r: r.needs_update == wanted)
        return [("id", "in", rows.ids)]

    @api.model
    def _deduct_for_receipt(self, move):
        """입고 확정된 이동 1건을 협력사 신고 재고에서 차감한다(이동당 1회, 0 아래로는 내려가지 않음)."""
        if move.supplier_inventory_deducted or move.state != "done":
            return self.browse()
        if move.location_id.usage != "supplier" or move.location_dest_id.usage != "internal":
            return self.browse()
        partner = (move.picking_id.partner_id or move.partner_id).commercial_partner_id
        if not partner or not partner.is_supplier_portal:
            return self.browse()
        # 차감 표시는 재고 행이 없어도 남긴다 — 나중에 행이 생겨도 과거 입고를 소급 차감하지 않는다.
        move.sudo().write({"supplier_inventory_deducted": True})
        inv = self.sudo().search([
            ("company_id", "=", move.company_id.id),
            ("partner_id.commercial_partner_id", "=", partner.id),
            ("product_id", "=", move.product_id.id),
        ], limit=1)
        qty = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id, round=False)
        if not inv or qty <= 0:
            return self.browse()
        inv.write({
            "quantity": max(0.0, inv.quantity - qty),
            "last_deduction_date": fields.Datetime.now(),
            "last_deduction_qty": qty,
        })
        inv._notify_update_needed(move)
        return inv

    def _notify_update_needed(self, move=None):
        """부족하면 포털 알림 + 메일. 같은 품목의 안 읽은 요청이 남아 있으면 다시 보내지 않는다."""
        Notification = self.env["supplier.portal.notification"].sudo()
        template = self.env.ref("supplier_portal_purchase.mail_template_supplier_inventory_update", raise_if_not_found=False)
        sent = self.browse()
        for rec in self.sudo():
            rec.invalidate_recordset(["outstanding_qty", "shortage_qty", "needs_update"])
            if not rec.needs_update:
                continue
            pending = Notification.search_count([
                ("company_id", "=", rec.company_id.id), ("partner_id", "=", rec.partner_id.id),
                ("product_id", "=", rec.product_id.id), ("notification_type", "=", "inventory_update"),
                ("is_read", "=", False)])
            if pending:
                continue
            Notification.create({
                "company_id": rec.company_id.id, "partner_id": rec.partner_id.id, "product_id": rec.product_id.id,
                "notification_type": "inventory_update",
                "message": _("[%(product)s] 재고 갱신 요청 — 신고 재고 %(qty)s, 미입고 요구량 %(need)s(부족 %(short)s). "
                             "%(ref)s 입고로 차감되었습니다. 생산 후 포털 '내 재고 관리'에서 재고를 다시 입력해 주세요.") % {
                    "product": rec.product_id.display_name, "qty": _fmt(rec.quantity), "need": _fmt(rec.outstanding_qty),
                    "short": _fmt(rec.shortage_qty), "ref": (move.picking_id.name if move is not None and move.picking_id else _("납품"))},
            })
            if template and (rec.partner_id.portal_notify_email or rec.partner_id.email):
                template.sudo().send_mail(rec.id, force_send=False)
            rec.write({"update_requested_at": fields.Datetime.now()})
            sent |= rec
        return sent


def _fmt(value):
    return ("%g" % value) if value is not None else "0"


class SupplierPortalNotification(models.Model):
    _inherit = "supplier.portal.notification"

    notification_type = fields.Selection(selection_add=[("inventory_update", "재고 갱신 요청")],
                                         ondelete={"inventory_update": "cascade"})


class StockMove(models.Model):
    _inherit = "stock.move"

    supplier_inventory_deducted = fields.Boolean(string="협력사 재고 차감됨", readonly=True, copy=False,
                                                 help="이 입고 이동으로 협력사 신고 재고를 이미 차감했다(멱등 표시).")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        res = super().button_validate()
        Inventory = self.env["supplier.inventory"]
        for picking in self.filtered(lambda p: p.state == "done" and p.picking_type_code == "incoming"):
            for move in picking.move_ids.filtered(lambda m: m.state == "done"):
                Inventory._deduct_for_receipt(move)
        return res
