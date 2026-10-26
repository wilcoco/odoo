"""무발주 소요통보 잔량을 협력사 재고 '미입고 요구량'에 더한다 (supplier_portal_purchase 재고 연동)."""
from odoo import models


class SupplierInventory(models.Model):
    _inherit = "supplier.inventory"

    def _outstanding_quantity(self):
        total = super()._outstanding_quantity()
        commercial = self.partner_id.commercial_partner_id
        notices = self.env["scm.no.po.notice"].sudo().search([
            ("company_id", "=", self.company_id.id), ("product_id", "=", self.product_id.id), ("state", "=", "issued"),
        ]).filtered(lambda n: n.partner_id.commercial_partner_id == commercial)
        for notice in notices:
            remaining = max(0.0, notice.quantity - notice.received_quantity)
            if remaining:
                total += notice.uom_id._compute_quantity(remaining, self.product_id.uom_id, round=False)
        return total
