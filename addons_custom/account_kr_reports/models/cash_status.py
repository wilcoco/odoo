from odoo import api, fields, models, _


class KrCashStatus(models.TransientModel):
    """리포트 #21: 은행/현금 저널별 잔액·오늘 입출금·미처리 결제 — 자금현황."""
    _name = "kr.cash.status"
    _description = "자금현황"

    line_ids = fields.One2many("kr.cash.status.line", "status_id", string="계좌별 현황")
    total_balance = fields.Monetary(string="총 잔액", currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    pending_payments = fields.Integer(string="미전기 결제")

    @api.model
    def action_open(self):
        rec = self.create({})
        rec._fill()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": rec.id,
                "view_mode": "form", "target": "current", "name": _("자금현황")}

    def _fill(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        Journal = self.env["account.journal"]
        AML = self.env["account.move.line"]
        total = 0.0
        lines = []
        for j in Journal.search([("type", "in", ("bank", "cash"))]):
            acc = j.default_account_id
            if not acc:
                continue
            bal_data = AML.read_group(
                [("account_id", "=", acc.id), ("parent_state", "=", "posted")],
                ["balance:sum"], [])
            balance = bal_data[0]["balance"] if bal_data and bal_data[0]["balance"] else 0.0
            today_dom = [("account_id", "=", acc.id), ("parent_state", "=", "posted"),
                         ("date", "=", today)]
            tin = AML.read_group(today_dom + [("debit", ">", 0)], ["debit:sum"], [])
            tout = AML.read_group(today_dom + [("credit", ">", 0)], ["credit:sum"], [])
            lines.append((0, 0, {
                "journal_id": j.id,
                "balance": balance,
                "today_in": tin[0]["debit"] if tin and tin[0]["debit"] else 0.0,
                "today_out": tout[0]["credit"] if tout and tout[0]["credit"] else 0.0,
            }))
            total += balance
        self.write({
            "line_ids": lines,
            "total_balance": total,
            "pending_payments": self.env["account.payment"].search_count([("state", "=", "draft")]),
        })

    def action_pending_payments(self):
        return {"type": "ir.actions.act_window", "res_model": "account.payment",
                "view_mode": "list,form", "name": _("미전기 결제"),
                "domain": [("state", "=", "draft")]}


class KrCashStatusLine(models.TransientModel):
    _name = "kr.cash.status.line"
    _description = "자금현황 라인"

    status_id = fields.Many2one("kr.cash.status", required=True, ondelete="cascade")
    journal_id = fields.Many2one("account.journal", string="계좌/저널")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)
    balance = fields.Monetary(string="잔액")
    today_in = fields.Monetary(string="오늘 입금")
    today_out = fields.Monetary(string="오늘 출금")
