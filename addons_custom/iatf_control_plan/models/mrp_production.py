from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    control_plan_id = fields.Many2one("iatf.control.plan", string="관리계획서", tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._auto_link_control_plan()
        return records

    def _auto_link_control_plan(self):
        """MO 생성 시 해당 제품의 승인된 관리계획서 자동 연결"""
        if self.control_plan_id:
            return
        # 생산 담당자에게 기준정보 편집 권한을 주지 않고 승인본 자동 연결만 수행.
        # sudo 조회는 해당 MO의 회사로 한정한다.
        cp = self.env["iatf.control.plan"].sudo().search([
            ("company_id", "in", [False, self.company_id.id]),
            ("product_id", "=", self.product_id.id),
            ("cp_type", "=", "production"),
            ("state", "=", "approved"),
        ], order="create_date desc", limit=1)
        if cp:
            self.control_plan_id = cp.id
            self.message_post(body=_("관리계획서 %s 자동 연결됨") % cp.name)
            _logger.info("Control Plan %s auto-linked to MO %s", cp.name, self.name)

    def action_view_control_plan(self):
        self.ensure_one()
        if self.control_plan_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "iatf.control.plan",
                "res_id": self.control_plan_id.id,
                "view_mode": "form",
                "target": "current",
            }
