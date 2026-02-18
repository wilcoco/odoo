from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    operator_qualified = fields.Boolean(
        compute="_compute_operator_qualified", string="작업자 자격 적합",
    )

    def _compute_operator_qualified(self):
        CompMatrix = self.env.get("iatf.competence.matrix")
        for rec in self:
            if CompMatrix is None or not rec.user_id:
                rec.operator_qualified = True
                continue
            # 해당 작업자의 역량 갭 확인
            gaps = CompMatrix.search([
                ("employee_id.user_id", "=", rec.user_id.id),
                ("gap", "=", True),
            ])
            rec.operator_qualified = len(gaps) == 0

    def button_mark_done(self):
        """MO 완료 시 작업자 자격 검증 경고"""
        for production in self:
            if not production.operator_qualified and production.user_id:
                production.message_post(
                    body=_("⚠ 작업자 %s의 역량 갭이 감지되었습니다. 교육 이수 확인이 필요합니다.") % production.user_id.name,
                    subject=_("작업자 자격 경고"),
                )
        return super().button_mark_done()
