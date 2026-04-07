from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrderRejectWizard(models.TransientModel):
    """발주 응답 반려 위자드"""
    _name = "purchase.order.reject.wizard"
    _description = "발주 응답 반려"

    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="발주서",
        required=True,
    )
    reject_reason = fields.Text(
        string="반려 사유",
        required=True,
    )

    def action_reject(self):
        """응답 반려 처리"""
        self.ensure_one()

        po = self.purchase_order_id
        if po.portal_state != "responded":
            raise UserError(_("응답 완료 상태의 발주만 반려할 수 있습니다."))

        # 최신 응답에 반려 사유 기록
        if po.latest_response_id:
            po.latest_response_id.write({
                "review_state": "rejected",
                "reviewed_by": self.env.user.id,
                "reviewed_date": fields.Datetime.now(),
                "reject_reason": self.reject_reason,
            })

        # PO 상태 변경
        po.portal_state = "rejected"

        # 협력사에게 반려 알림
        po._create_portal_notification("rejected", partner=po.partner_id)

        po.message_post(
            body=_("협력사 응답이 반려되었습니다.\n사유: %s") % self.reject_reason
        )

        return {"type": "ir.actions.act_window_close"}
