from odoo import fields, models


class EngelDefectType(models.Model):
    _name = "engel.defect.type"
    _description = "사출 불량 유형"
    _order = "code"

    code = fields.Char(string="불량 코드", required=True)
    name = fields.Char(string="불량명", required=True)
    description = fields.Text(string="설명")
    active = fields.Boolean(string="활성", default=True)
