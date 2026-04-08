from odoo import api, fields, models


class ProductProduct(models.Model):
    """제품에 외주 정보 추가 (실제 저장)"""
    _inherit = "product.product"

    is_outsourced = fields.Boolean(
        string="외주 부품",
        default=False,
        help="외부 협력사에서 조달하는 부품인 경우 체크",
    )
    outsource_partner_id = fields.Many2one(
        "res.partner",
        string="기본 협력사",
        domain="[('is_supplier_portal', '=', True)]",
        help="이 부품의 기본 외주 협력사",
    )
    outsource_leadtime = fields.Integer(
        string="외주 리드타임 (일)",
        default=3,
        help="발주부터 입고까지 소요 기간",
    )


class ProductTemplate(models.Model):
    """제품 템플릿에 외주 정보 추가 (뷰용 - 저장 안함)"""
    _inherit = "product.template"

    is_outsourced = fields.Boolean(
        string="외주 부품",
        compute="_compute_outsource_fields",
        inverse="_inverse_outsource_fields",
    )
    outsource_partner_id = fields.Many2one(
        "res.partner",
        string="기본 협력사",
        compute="_compute_outsource_fields",
        inverse="_inverse_outsource_fields",
    )
    outsource_leadtime = fields.Integer(
        string="외주 리드타임 (일)",
        compute="_compute_outsource_fields",
        inverse="_inverse_outsource_fields",
    )

    @api.depends("product_variant_ids.is_outsourced")
    def _compute_outsource_fields(self):
        for tmpl in self:
            variant = tmpl.product_variant_ids[:1]
            tmpl.is_outsourced = variant.is_outsourced if variant else False
            tmpl.outsource_partner_id = variant.outsource_partner_id if variant else False
            tmpl.outsource_leadtime = variant.outsource_leadtime if variant else 3

    def _inverse_outsource_fields(self):
        for tmpl in self:
            for variant in tmpl.product_variant_ids:
                variant.write({
                    "is_outsourced": tmpl.is_outsourced,
                    "outsource_partner_id": tmpl.outsource_partner_id.id if tmpl.outsource_partner_id else False,
                    "outsource_leadtime": tmpl.outsource_leadtime,
                })
