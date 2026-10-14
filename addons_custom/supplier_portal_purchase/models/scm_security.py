from odoo import api, fields, models
from .scm_utils import check_actor


class SupplyChainOrder(models.Model):
    _inherit = "supply.chain.order"
    company_id = fields.Many2one(related="purchase_order_id.company_id", store=True, index=True)


class SupplyChainOrderStatus(models.Model):
    _inherit = "supply.chain.order.status"
    company_id = fields.Many2one(related="chain_order_id.company_id", store=True, index=True)

    def write(self, vals):
        for record in self:
            check_actor(record, record.supplier_id)
        result = super().write(vals)
        for record in self:
            check_actor(record, record.supplier_id)
        return result


class SupplierPortalNotification(models.Model):
    _inherit = "supplier.portal.notification"
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("purchase_order_id"):
                vals["company_id"] = self.env["purchase.order"].browse(vals["purchase_order_id"]).company_id.id
        return super().create(vals_list)
