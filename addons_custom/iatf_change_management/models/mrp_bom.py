from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    change_locked = fields.Boolean(string="변경 잠금", default=False,
                                    help="미승인 CR 존재 시 True")

    def write(self, vals):
        """BOM 변경 시 자동으로 변경요청(CR) 생성 + 미승인 CR 존재 시 차단 (L3-4)"""
        change_fields = {"bom_line_ids", "product_tmpl_id", "product_qty",
                         "routing_id", "operation_ids", "type"}
        trigger_fields = set(vals.keys()) & change_fields

        # 미승인 CR 존재 시 BOM 변경 차단
        if trigger_fields and "change_locked" not in vals:
            CR = self.env.get("iatf.change.request")
            if CR:
                for rec in self:
                    pending_crs = CR.search([
                        ("affected_product_ids", "in", rec.product_tmpl_id.product_variant_ids.ids),
                        ("state", "not in", ("approved", "closed", "cancelled")),
                    ])
                    if pending_crs:
                        raise UserError(_(
                            "미승인 변경요청(CR)이 존재하여 BOM을 수정할 수 없습니다.\n"
                            "CR 승인 후 BOM을 수정하세요.\n"
                            "관련 CR: %s") % ", ".join(pending_crs.mapped("name")))
        old_values = {}
        if trigger_fields:
            for rec in self:
                old_values[rec.id] = {
                    "product": rec.product_tmpl_id.name,
                    "qty": rec.product_qty,
                    "lines": len(rec.bom_line_ids),
                }

        res = super().write(vals)

        if trigger_fields:
            for rec in self:
                old = old_values.get(rec.id, {})
                changed_desc = ", ".join(trigger_fields)
                self.env["iatf.change.request"].create({
                    "title": _("BOM 변경: %s") % rec.product_tmpl_id.name,
                    "change_type": "method",
                    "change_category": "planned",
                    "change_source": "engineering",
                    "description": "<p>BOM 자동 변경 감지<br/>제품: %s<br/>변경 필드: %s</p>" % (
                        rec.product_tmpl_id.name, changed_desc),
                    "reason": "<p>BOM 수정에 의한 자동 생성</p>",
                    "affected_product_ids": [(6, 0, rec.product_tmpl_id.product_variant_ids.ids)],
                    "before_state": "<p>%s</p>" % str(old) if old else False,
                    "risk_level": "medium",
                })
                _logger.info("Change Request auto-created for BOM %s change", rec.display_name)

        return res
