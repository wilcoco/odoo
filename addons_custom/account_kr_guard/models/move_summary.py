from odoo import api, fields, models


class AccountMove(models.Model):
    """리포트 #4·#14: 청구서에서 받은/남은 금액이 한눈에."""
    _inherit = "account.move"

    kr_paid_amount = fields.Monetary(string="결제 완료 금액", compute="_compute_kr_amounts")
    kr_residual_display = fields.Monetary(string="남은 금액", compute="_compute_kr_amounts")

    @api.depends("amount_total", "amount_residual", "state")
    def _compute_kr_amounts(self):
        for mv in self:
            if mv.is_invoice(include_receipts=True) and mv.state == "posted":
                mv.kr_paid_amount = mv.amount_total - mv.amount_residual
                mv.kr_residual_display = mv.amount_residual
            else:
                mv.kr_paid_amount = 0.0
                mv.kr_residual_display = mv.amount_total if mv.is_invoice(True) else 0.0
