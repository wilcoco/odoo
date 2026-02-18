from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    def write(self, vals):
        """BOM 변경 시 자동으로 변경요청(CR) 생성"""
        # 변경 전 상태 기록
        change_fields = {"bom_line_ids", "product_tmpl_id", "product_qty",
                         "routing_id", "operation_ids", "type"}
        trigger_fields = set(vals.keys()) & change_fields
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
