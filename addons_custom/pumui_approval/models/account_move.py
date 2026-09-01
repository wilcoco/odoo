from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountMove(models.Model):
    _inherit = "account.move"

    pumui_id = fields.Many2one(
        "pumui.request",
        string="품의서",
        copy=False,
        index=True,
        tracking=True,
        check_company=True,
        ondelete="restrict",
        help=(
            "이 청구서의 근거 품의서입니다. 품의서에서 생성한 청구서는 자동으로 "
            "연결되고, 별도로 작성한 공급업체 청구서는 초안에서 직접 연결할 수 있습니다."
        ),
    )
    pumui_approval_state = fields.Selection(related="pumui_id.approval_state",
                                            string="품의 승인상태", store=True)
    pumui_amount_diff = fields.Monetary(
        string="품의-청구 차이", compute="_compute_pumui_diff",
        help=(
            "품의 승인 총액에서 취소되지 않은 전체 연결 청구서 금액과 미청구 "
            "잔액을 뺀 값입니다. 음수이면 승인 금액을 초과했습니다."
        ))

    @api.depends("pumui_id.amount_diff")
    def _compute_pumui_diff(self):
        for mv in self:
            mv.pumui_amount_diff = mv.pumui_id.amount_diff if mv.pumui_id else 0.0

    @api.constrains("pumui_id", "move_type", "partner_id", "company_id")
    def _check_pumui_scope(self):
        """품의 종류·거래처·회사가 다른 청구서에 잘못 연결되지 않게 한다."""
        purchase_types = {"in_invoice", "in_refund"}
        sale_types = {"out_invoice", "out_refund"}
        for move in self.filtered("pumui_id"):
            request = move.pumui_id
            if (
                move.move_type in purchase_types
                and request.pumui_type != "purchase"
            ) or (
                move.move_type in sale_types
                and request.pumui_type != "sale"
            ) or move.move_type not in purchase_types | sale_types:
                raise ValidationError(_(
                    "청구서 유형과 품의 구분이 일치하지 않습니다. "
                    "공급업체 청구서는 지출 품의에 연결해 주세요."
                ))
            if request.company_id != move.company_id:
                raise ValidationError(_(
                    "청구서와 품의서는 같은 회사에 속해야 합니다."
                ))
            if (
                move.partner_id
                and request.partner_id.commercial_partner_id
                != move.partner_id.commercial_partner_id
            ):
                raise ValidationError(_(
                    "청구서 거래처와 품의서 거래처가 일치해야 합니다."
                ))

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
