from odoo import api, fields, models, _


class StockPicking(models.Model):
    _inherit = "stock.picking"

    packaging_verified = fields.Boolean(string="포장사양 검증됨", default=False)
    packaging_spec_ids = fields.Many2many(
        "iatf.packaging.spec", compute="_compute_packaging_specs",
    )
    packaging_spec_count = fields.Integer(compute="_compute_packaging_specs")

    def _compute_packaging_specs(self):
        PkgSpec = self.env.get("iatf.packaging.spec")
        for rec in self:
            if PkgSpec is None or rec.picking_type_code != "outgoing":
                rec.packaging_spec_ids = False
                rec.packaging_spec_count = 0
                continue
            product_ids = rec.move_ids.mapped("product_id").ids
            specs = PkgSpec.search([
                ("product_id", "in", product_ids),
                ("state", "=", "active"),
            ])
            rec.packaging_spec_ids = specs
            rec.packaging_spec_count = len(specs)

    def button_validate(self):
        for picking in self:
            if picking.picking_type_code == "outgoing":
                picking._check_packaging_spec()
        return super().button_validate()

    def _check_packaging_spec(self):
        """출하 시 포장사양 검증 경고 (L2-20)"""
        PkgSpec = self.env.get("iatf.packaging.spec")
        if PkgSpec is None:
            return
        for move in self.move_ids.filtered(lambda m: m.product_id.type != "service"):
            specs = PkgSpec.search([
                ("product_id", "=", move.product_id.id),
                ("state", "=", "active"),
            ])
            if specs and not self.packaging_verified:
                self.message_post(
                    body=_("⚠ 제품 '%s'에 대한 포장사양서가 존재합니다. 포장 상태를 확인하세요. (사양서: %s)") % (
                        move.product_id.name, ", ".join(specs.mapped("name"))),
                    subject=_("포장사양 확인 필요"),
                )

    def action_view_packaging_specs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.packaging.spec",
            "view_mode": "list,form",
            "domain": [("id", "in", self.packaging_spec_ids.ids)],
            "name": _("포장사양서"),
        }
