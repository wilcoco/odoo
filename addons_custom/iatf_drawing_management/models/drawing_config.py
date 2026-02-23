from odoo import fields, models


class IatfDrawingConfig(models.Model):
    _name = "iatf.drawing.config"
    _description = "도면관리 선택 옵션"
    _order = "config_type, sequence, name"

    name = fields.Char(string="옵션명", required=True)
    config_type = fields.Selection(
        [
            ("product_group", "제품군"),
            ("drawing_type", "도면 구분"),
            ("product_standard", "제품 기준"),
            ("category_item", "구분 항목"),
            ("car_model", "차종"),
            ("specification", "사양"),
            ("retention_year", "보존 년한"),
            ("document_status", "문서 상태"),
            ("change_type", "변경 구분(4M+E)"),
        ],
        string="옵션 구분",
        required=True,
    )
    sequence = fields.Integer(string="표시 순서", default=10)
    active = fields.Boolean(default=True)
    note = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
