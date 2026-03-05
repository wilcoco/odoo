from odoo import fields, models


class EngelCarModel(models.Model):
    _name = "engel.car.model"
    _description = "차종 마스터"
    _order = "name"

    name = fields.Char(string="차종명", required=True)
    code = fields.Char(string="코드", required=True)
    customer_id = fields.Many2one("res.partner", string="고객사")
    active = fields.Boolean(string="활성", default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "차종 코드는 고유해야 합니다."),
    ]
