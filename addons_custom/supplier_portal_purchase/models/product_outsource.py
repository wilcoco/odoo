from odoo import api, fields, models


class ProductTemplate(models.Model):
    """제품 템플릿에 외주 정보 추가"""
    _inherit = "product.template"

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


class ProductProduct(models.Model):
    """제품 변형에 외주 정보 추가 (템플릿에서 상속)"""
    _inherit = "product.product"

    is_outsourced = fields.Boolean(
        string="외주 부품",
        related="product_tmpl_id.is_outsourced",
        store=True,
        readonly=False,
    )
    outsource_partner_id = fields.Many2one(
        "res.partner",
        string="기본 협력사",
        related="product_tmpl_id.outsource_partner_id",
        store=True,
        readonly=False,
    )
    outsource_leadtime = fields.Integer(
        string="외주 리드타임 (일)",
        related="product_tmpl_id.outsource_leadtime",
        store=True,
        readonly=False,
    )
