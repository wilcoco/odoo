from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    default_car_model_id = fields.Many2one(
        "engel.car.model", string="기본 차종",
        help="MO 생성 시 자동 입력될 기본 차종",
    )
