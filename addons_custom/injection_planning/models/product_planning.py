from odoo import api, fields, models


class ProductPlanning(models.Model):
    _inherit = "product.product"

    injection_base_code = fields.Char(
        string="사출 기준코드",
        index=True,
        help="완제품 품번에서 도장 컬러코드(뒤 3자리)를 제외한 코드. "
             "같은 기준코드를 가진 완제품은 동일한 사출 BOM을 공유합니다. "
             "예: 86500-BS000EBB → 기준코드 86500-BS000",
    )
    max_inventory_qty = fields.Float(
        string="최대 재고량",
        help="이 제품의 최대 재고 한계 수량. 0이면 제한 없음.",
    )
    min_lot_size = fields.Integer(
        string="최소 로트 크기",
        help="생산 시 최소 로트 수량. 0이면 제한 없음.",
    )
