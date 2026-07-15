from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    pumui_id = fields.Many2one("pumui.request", string="품의서", copy=False, index=True,
                               help="이 청구서의 근거 품의서 (승인 후 생성)")
    pumui_approval_state = fields.Selection(related="pumui_id.approval_state",
                                            string="품의 승인상태", store=True)
    pumui_amount_diff = fields.Monetary(
        string="품의-청구 차이", compute="_compute_pumui_diff",
        help="품의 승인 총액 대비 이 청구서 금액 차이 (리포트 #6: 차이 안내)")

    @api.depends("pumui_id.amount_total", "amount_total")
    def _compute_pumui_diff(self):
        for mv in self:
            mv.pumui_amount_diff = (
                (mv.pumui_id.amount_total - mv.amount_total) if mv.pumui_id else 0.0)

    def action_post(self):
        """승인 전 지급/전기 차단 (리포트 #7). 품의 연계 청구서는 승인 완료가 전기 조건."""
        for mv in self:
            if mv.pumui_id and mv.pumui_id.approval_state != "approved":
                raise UserError(_(
                    "품의서 %(p)s 가 아직 승인되지 않았습니다(현재: %(s)s). "
                    "승인 완료 후 전기할 수 있습니다.") % {
                        "p": mv.pumui_id.name,
                        "s": dict(mv.pumui_id._fields["approval_state"]._description_selection(
                            self.env)).get(mv.pumui_id.approval_state, "-")})
        return super().action_post()
