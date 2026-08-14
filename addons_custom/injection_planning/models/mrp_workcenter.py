from odoo import fields, models


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    x_clamping_force_ton = fields.Float(
        string="형체력 (톤)",
        help="사출기 형체력(톤). 배정 시 금형의 요구 형체력 이상인 사출기만 적합 판정. "
             "0이면 적합성 필터 미적용(등록 전 방어).",
    )
