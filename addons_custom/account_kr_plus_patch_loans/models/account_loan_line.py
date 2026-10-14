from odoo import _, api, fields, models


class AccountLoanLine(models.Model):
    """상환 일정 회차에 실제로 계상된 전표를 연결해 대장과 원장을 대조한다."""

    _inherit = "account.loan.line"

    kr_actual_move_ids = fields.Many2many(
        "account.move",
        "account_loan_line_kr_actual_move_rel",
        "line_id",
        "move_id",
        string="실제 전표",
        help="이 회차에 해당하는 실제 이자·상환 전표입니다. 이관 자료로 올라온 전표를 연결합니다.",
    )
    kr_capitalize_account_id = fields.Many2one(
        "account.account",
        string="이자 자본화 계정",
        help="건설자금이자처럼 이자를 비용이 아니라 자산 원가에 가산한 경우의 계정입니다. "
        "실제 이자 대조에 사용합니다.",
    )
    kr_actual_interest = fields.Monetary(
        string="실제 이자", compute="_compute_kr_actual_interest", store=False,
    )
    kr_interest_diff = fields.Monetary(
        string="이자 차이", compute="_compute_kr_actual_interest", store=False,
        help="회차 이자 − 실제 전표에 계상된 이자. 0이면 대장과 원장이 맞습니다.",
    )

    @api.depends(
        "interest",
        "kr_actual_move_ids.line_ids.debit",
        "kr_actual_move_ids.line_ids.credit",
        "kr_actual_move_ids.line_ids.account_id",
        "kr_capitalize_account_id",
        "loan_id.expense_account_id",
    )
    def _compute_kr_actual_interest(self):
        for line in self:
            accounts = line.loan_id.expense_account_id | line.kr_capitalize_account_id
            total = 0.0
            if accounts:
                for move_line in line.kr_actual_move_ids.line_ids:
                    if move_line.account_id in accounts:
                        total += move_line.debit - move_line.credit
            line.kr_actual_interest = total
            line.kr_interest_diff = line.interest - total

    def action_kr_open_actual_moves(self):
        self.ensure_one()
        return {
            "name": _("실제 전표"),
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.kr_actual_move_ids.ids)],
        }
