from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrContract(models.Model):
    _inherit = "hr.contract"

    kr_retirement_plan = fields.Selection(
        [("severance", "퇴직금"), ("db", "퇴직연금 DB형"), ("dc", "퇴직연금 DC형")],
        string="퇴직급여 제도", default="severance",
        help="DC형은 납입 대장으로 관리, 퇴직금/DB형은 퇴직금 계산서로 산정")


class KrSeveranceEstimate(models.Model):
    """퇴직금(법정) 계산서 — 평균임금 기준.
    3개월 임금은 급여명세서에서 자동 집계(수정 가능), 상여·연차수당 가산분은 입력.
    평균임금 = (3개월 임금총액 + 연간상여×3/12 + 연차수당×3/12) ÷ 3개월 역일수
    퇴직금 = 평균임금 × 30일 × (재직일수 ÷ 365)"""
    _name = "kr.severance.estimate"
    _description = "퇴직금 계산서"
    _inherit = ["mail.thread"]
    _order = "date_leave desc, id desc"

    employee_id = fields.Many2one("hr.employee", string="직원", required=True, tracking=True)
    contract_id = fields.Many2one("hr.contract", string="계약", compute="_compute_contract", store=True)
    plan_type = fields.Selection(related="contract_id.kr_retirement_plan", string="제도")
    date_join = fields.Date(string="입사일", compute="_compute_contract", store=True, readonly=False)
    date_leave = fields.Date(string="퇴직일", required=True, tracking=True,
                             help="마지막 근무일의 다음날 (재직일수 = 퇴직일 − 입사일)")
    service_days = fields.Integer(string="재직일수", compute="_compute_amounts", store=True)
    months3_wage = fields.Float(
        string="퇴직 전 3개월 임금총액", tracking=True,
        help="'급여에서 집계' 버튼으로 명세서 자동 합산 — 수기 조정 가능")
    months3_days = fields.Integer(string="3개월 역일수", compute="_compute_amounts", store=True)
    annual_bonus = fields.Float(string="연간 상여 총액", help="3/12 가산 — 규정상 미포함이면 0")
    annual_leave_pay = fields.Float(string="연차수당(연간)", help="3/12 가산 — 규정상 미포함이면 0")
    avg_daily_wage = fields.Float(string="평균임금(1일)", compute="_compute_amounts", store=True)
    severance_amount = fields.Float(string="퇴직금(법정)", compute="_compute_amounts", store=True, tracking=True)
    state = fields.Selection([("draft", "초안"), ("confirmed", "확정")], default="draft", tracking=True)
    note = fields.Text(string="비고")

    @api.depends("employee_id")
    def _compute_contract(self):
        for rec in self:
            contract = rec.employee_id.contract_ids.sorted("date_start", reverse=True)[:1]
            rec.contract_id = contract
            rec.date_join = rec.date_join or (contract.date_start if contract else False)

    @api.depends("date_join", "date_leave", "months3_wage", "annual_bonus", "annual_leave_pay")
    def _compute_amounts(self):
        for rec in self:
            if not (rec.date_join and rec.date_leave and rec.date_leave > rec.date_join):
                rec.service_days = rec.months3_days = 0
                rec.avg_daily_wage = rec.severance_amount = 0.0
                continue
            rec.service_days = (rec.date_leave - rec.date_join).days
            period_start = rec.date_leave - relativedelta(months=3)
            rec.months3_days = (rec.date_leave - period_start).days
            total = (rec.months3_wage
                     + rec.annual_bonus * 3.0 / 12.0
                     + rec.annual_leave_pay * 3.0 / 12.0)
            rec.avg_daily_wage = round(total / rec.months3_days) if rec.months3_days else 0.0
            # 재직 1년 미만은 법정 지급의무 없음 — 0 (회사 규정 지급 시 수기)
            if rec.service_days < 365:
                rec.severance_amount = 0.0
            else:
                rec.severance_amount = round(rec.avg_daily_wage * 30 * rec.service_days / 365.0)

    def action_fill_from_payslips(self):
        """퇴직 전 3개월 GROSS 를 확정 명세서에서 집계."""
        for rec in self:
            if not rec.date_leave:
                raise UserError(_("퇴직일을 먼저 입력하세요."))
            period_start = rec.date_leave - relativedelta(months=3)
            slips = self.env["hr.payslip"].search([
                ("employee_id", "=", rec.employee_id.id),
                ("state", "not in", ("draft", "cancel")),
                ("date_from", ">=", period_start), ("date_to", "<", rec.date_leave),
            ])
            gross = sum(l.total for l in slips.line_ids.filtered(lambda l: l.code == "GROSS"))
            if not gross:
                raise UserError(_("해당 3개월 구간의 확정 급여명세서가 없습니다. 임금총액을 직접 입력하세요."))
            rec.months3_wage = gross
        return True

    def action_confirm(self):
        for rec in self:
            if not rec.severance_amount and rec.service_days >= 365:
                raise UserError(_("퇴직금이 0입니다. 임금총액을 입력/집계 후 확정하세요."))
            rec.state = "confirmed"


class KrRetirementContribution(models.Model):
    """퇴직연금 DC형 납입 대장 — 연간 임금총액의 1/12 이상 납입 점검용."""
    _name = "kr.retirement.contribution"
    _description = "퇴직연금(DC) 납입 대장"
    _order = "date desc, id desc"

    employee_id = fields.Many2one("hr.employee", string="직원", required=True)
    date = fields.Date(string="납입일", required=True, default=fields.Date.context_today)
    year = fields.Integer(string="귀속연도", compute="_compute_year", store=True)
    amount = fields.Float(string="납입액", required=True)
    institution = fields.Char(string="금융기관")
    annual_wage = fields.Float(string="연간 임금총액(참고)",
                               help="해당 연도 임금총액 — 필요 납입액(1/12) 비교용")
    required_amount = fields.Float(string="연 필요 납입액(1/12)", compute="_compute_required", store=True)
    note = fields.Char(string="비고")

    @api.depends("date")
    def _compute_year(self):
        for rec in self:
            rec.year = rec.date.year if rec.date else 0

    @api.depends("annual_wage")
    def _compute_required(self):
        for rec in self:
            rec.required_amount = round(rec.annual_wage / 12.0) if rec.annual_wage else 0.0
