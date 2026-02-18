from odoo import api, fields, models, _


class SaleOrder(models.Model):
    _inherit = "sale.order"

    csr_warning = fields.Boolean(compute="_compute_csr_warning")
    csr_count = fields.Integer(compute="_compute_csr_warning")

    @api.depends("partner_id", "order_line.product_id")
    def _compute_csr_warning(self):
        CSR = self.env.get("iatf.csr")
        for rec in self:
            if CSR is None or not rec.partner_id:
                rec.csr_warning = False
                rec.csr_count = 0
                continue
            product_ids = rec.order_line.mapped("product_id").ids
            csrs = CSR.search([
                ("customer_id", "=", rec.partner_id.id),
                ("state", "=", "active"),
                "|",
                ("applies_to_all", "=", True),
                ("product_ids", "in", product_ids),
            ])
            rec.csr_count = len(csrs)
            rec.csr_warning = len(csrs) > 0

    @api.onchange("partner_id")
    def _onchange_partner_csr_check(self):
        if not self.partner_id:
            return
        CSR = self.env.get("iatf.csr")
        if CSR is None:
            return
        csrs = CSR.search([
            ("customer_id", "=", self.partner_id.id),
            ("state", "=", "active"),
        ])
        if csrs:
            names = ", ".join(csrs.mapped("name"))
            return {
                "warning": {
                    "title": _("⚠ 고객 특수요구사항 (CSR) 존재"),
                    "message": _(
                        "고객 '%s'에 대한 활성 CSR이 %d건 있습니다.\n"
                        "해당 요구사항을 확인하세요: %s"
                    ) % (self.partner_id.name, len(csrs), names),
                }
            }

    def action_view_csrs(self):
        self.ensure_one()
        product_ids = self.order_line.mapped("product_id").ids
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.csr",
            "view_mode": "list,form",
            "name": _("고객 특수요구사항"),
            "domain": [
                ("customer_id", "=", self.partner_id.id),
                ("state", "=", "active"),
                "|",
                ("applies_to_all", "=", True),
                ("product_ids", "in", product_ids),
            ],
        }
