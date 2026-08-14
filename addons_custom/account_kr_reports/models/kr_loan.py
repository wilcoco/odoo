from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class KrLoan(models.Model):
    """리포트 #25: 대출 관리 — 약정 조건을 코드가 아니라 입력으로 받는다.
    지급 방식: 매월/만기 일시/1회/사용자 지정 스케줄."""
    _name = "kr.loan"
    _description = "대출 관리"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"

    name = fields.Char(string="대출명", required=True, tracking=True)
    partner_id = fields.Many2one("res.partner", string="거래처(대주)", required=True, tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    currency_id = fields.Many2one(related="company_id.currency_id")
    principal = fields.Monetary(string="원금", required=True, tracking=True)
    interest_rate = fields.Float(string="이자율 (%/년)", digits=(6, 3), tracking=True)
    date_start = fields.Date(string="차입일", required=True, default=fields.Date.context_today)
    maturity_date = fields.Date(string="만기일")
    payment_mode = fields.Selection(
        [("monthly", "매월 이자 지급 (원금 만기)"), ("maturity", "만기 일시 지급"),
         ("once", "1회 지급"), ("custom", "사용자 지정 스케줄")],
        string="지급 방식", required=True, default="monthly", tracking=True,
        help="캠스처럼 매월 지급이 아닌 경우 '사용자 지정'으로 실제 약정 스케줄을 직접 입력")
    schedule_ids = fields.One2many("kr.loan.schedule", "loan_id", string="지급 스케줄")
    total_interest = fields.Monetary(string="총 이자(스케줄 합)", compute="_compute_totals", store=True)
    paid_principal = fields.Monetary(string="상환 원금", compute="_compute_totals", store=True)
    paid_interest = fields.Monetary(string="지급 이자", compute="_compute_totals", store=True)
    balance = fields.Monetary(string="원금 잔액", compute="_compute_totals", store=True)
    state = fields.Selection(
        [("draft", "약정"), ("active", "진행"), ("closed", "상환 완료")],
        default="draft", string="상태", tracking=True)
    note = fields.Text(string="약정 조건 비고",
                       help="예: 당년도 발생 차입금은 연말 정리 후 차액을 상환/차환 시 적용")

    @api.depends("schedule_ids.amount_principal", "schedule_ids.amount_interest",
                 "schedule_ids.state", "principal")
    def _compute_totals(self):
        for loan in self:
            loan.total_interest = sum(loan.schedule_ids.mapped("amount_interest"))
            paid = loan.schedule_ids.filtered(lambda s: s.state == "paid")
            loan.paid_principal = sum(paid.mapped("amount_principal"))
            loan.paid_interest = sum(paid.mapped("amount_interest"))
            loan.balance = loan.principal - loan.paid_principal

    def action_generate_schedule(self):
        """지급 방식에 따라 스케줄 자동 생성 (custom 은 수기 입력)."""
        self.ensure_one()
        if self.payment_mode == "custom":
            raise UserError(_("사용자 지정 방식은 스케줄을 직접 입력하세요."))
        if not self.maturity_date:
            raise UserError(_("만기일을 입력하세요."))
        self.schedule_ids.filtered(lambda s: s.state == "planned").unlink()
        # 멱등: 이미 지급 완료된 회차(date_due)는 재생성하지 않고, 잔여 원금만 배분
        paid = self.schedule_ids.filtered(lambda s: s.state == "paid")
        paid_dates = set(paid.mapped("date_due"))
        remaining_principal = self.principal - sum(paid.mapped("amount_principal"))
        Sched = self.env["kr.loan.schedule"]
        yearly_interest = self.principal * (self.interest_rate / 100.0)
        if self.payment_mode == "monthly":
            months = max(1, (self.maturity_date.year - self.date_start.year) * 12
                         + self.maturity_date.month - self.date_start.month)
            monthly_int = yearly_interest / 12.0
            for i in range(1, months + 1):
                d = min(self.date_start + relativedelta(months=i), self.maturity_date)
                if d in paid_dates:
                    continue
                Sched.create({"loan_id": self.id, "date_due": d,
                              "amount_interest": monthly_int,
                              "amount_principal": remaining_principal if i == months else 0.0})
        else:  # maturity / once
            if self.maturity_date not in paid_dates:
                days = max(1, (self.maturity_date - self.date_start).days)
                interest = yearly_interest * days / 365.0
                Sched.create({"loan_id": self.id, "date_due": self.maturity_date,
                              "amount_interest": interest,
                              "amount_principal": remaining_principal})
        self.state = "active"
        return True

    def action_close(self):
        for loan in self:
            if loan.balance > 0:
                raise UserError(_("원금 잔액(%(b)s)이 남아 있습니다. 스케줄 지급 처리 후 종료하세요.")
                                % {"b": loan.balance})
        self.write({"state": "closed"})


class KrLoanSchedule(models.Model):
    _name = "kr.loan.schedule"
    _description = "대출 지급 스케줄"
    _order = "date_due, id"

    loan_id = fields.Many2one("kr.loan", required=True, ondelete="cascade")
    currency_id = fields.Many2one(related="loan_id.currency_id")
    date_due = fields.Date(string="지급 예정일", required=True)
    amount_principal = fields.Monetary(string="원금")
    amount_interest = fields.Monetary(string="이자")
    date_paid = fields.Date(string="실제 지급일")
    move_id = fields.Many2one("account.move", string="연결 전표/청구서")
    state = fields.Selection([("planned", "예정"), ("paid", "지급 완료")],
                             default="planned", string="상태")

    def action_mark_paid(self):
        for s in self:
            s.write({"state": "paid", "date_paid": s.date_paid or fields.Date.context_today(s)})
