from odoo import fields, models


class IatfInspectionCriteria(models.Model):
    _name = "iatf.inspection.criteria"
    _description = "수입검사 기준서"
    _order = "product_id, sequence"

    product_id = fields.Many2one("product.product", string="제품", required=True, index=True)
    supplier_id = fields.Many2one("res.partner", string="협력업체",
                                   domain="[('supplier_rank','>',0)]")
    sequence = fields.Integer(default=10)
    characteristic_name = fields.Char(string="검사 항목", required=True)
    characteristic_type = fields.Selection(
        [("dimensional", "치수"), ("visual", "외관"), ("functional", "기능"),
         ("material", "재질"), ("other", "기타")],
        string="항목 유형", default="dimensional",
    )
    specification = fields.Char(string="규격 / 공차", required=True)
    measurement_method = fields.Char(string="측정 방법")
    sampling_plan = fields.Char(string="샘플링 기준")
    is_critical = fields.Boolean(string="중요 특성")
    active = fields.Boolean(default=True)
    notes = fields.Text(string="비고")
