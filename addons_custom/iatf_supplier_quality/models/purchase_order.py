from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    supplier_grade = fields.Selection(related="partner_id.iatf_supplier_grade", string="업체 등급", readonly=True)
    supplier_grade_warning = fields.Boolean(compute="_compute_supplier_warning")

    @api.depends("partner_id")
    def _compute_supplier_warning(self):
        for rec in self:
            rec.supplier_grade_warning = rec.partner_id.iatf_supplier_grade == "d"

    @api.onchange("partner_id")
    def _onchange_partner_supplier_grade(self):
        if self.partner_id and self.partner_id.iatf_supplier_grade == "d":
            return {
                "warning": {
                    "title": _("⚠ 부적격 업체 경고"),
                    "message": _(
                        "협력업체 '%s'은(는) IATF 평가 D등급 (부적격) 업체입니다.\n"
                        "발주 전 품질팀 승인을 받으세요."
                    ) % self.partner_id.name,
                }
            }
        if self.partner_id and self.partner_id.iatf_supplier_grade == "c":
            return {
                "warning": {
                    "title": _("⚠ 조건부 승인 업체"),
                    "message": _(
                        "협력업체 '%s'은(는) IATF 평가 C등급 (조건부 승인) 업체입니다.\n"
                        "개선 상태를 확인하세요."
                    ) % self.partner_id.name,
                }
            }


class ResPartner(models.Model):
    _inherit = "res.partner"

    iatf_supplier_grade = fields.Selection(
        [
            ("a", "A — 우수"),
            ("b", "B — 승인"),
            ("c", "C — 조건부"),
            ("d", "D — 부적격"),
        ],
        string="IATF 업체 등급", tracking=True,
        compute="_compute_iatf_grade", store=True,
    )
    iatf_evaluation_ids = fields.One2many(
        "iatf.supplier.evaluation", "supplier_id", string="IATF 평가 이력",
    )
    iatf_scar_ids = fields.One2many(
        "iatf.scar", "supplier_id", string="SCAR 이력",
    )

    @api.depends("iatf_evaluation_ids.grade", "iatf_evaluation_ids.state")
    def _compute_iatf_grade(self):
        for rec in self:
            latest = self.env["iatf.supplier.evaluation"].search([
                ("supplier_id", "=", rec.id),
                ("state", "=", "confirmed"),
            ], order="evaluation_date desc", limit=1)
            rec.iatf_supplier_grade = latest.grade if latest else False
