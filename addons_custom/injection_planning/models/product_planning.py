from odoo import fields, models


class ProductPlanning(models.Model):
    _inherit = "product.product"

    max_inventory_qty = fields.Float(
        string="최대 재고량",
        help="이 제품의 최대 재고 한계 수량. 0이면 제한 없음.",
    )
    min_lot_size = fields.Integer(
        string="최소 로트 크기",
        help="생산 시 최소 로트 수량. 0이면 제한 없음.",
    )
