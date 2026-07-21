from datetime import timedelta

from odoo import api, fields, models

RATE_CODES = [
    ("national_pension", "국민연금"),
    ("health", "건강보험"),
    ("long_term_care", "장기요양보험 (건강보험료 대비 %)"),
    ("employment", "고용보험"),
    ("industrial_accident", "산재보험 (회사 전액)"),
]


class KrPayrollRate(models.Model):
    """4대보험 요율 마스터 — 유효기간 기반. 매년 요율 변경 시 코드 수정 없이
    새 기간 행을 추가한다 (단가 이력과 동일 패턴)."""
    _name = "kr.payroll.rate"
    _description = "한국 4대보험 요율"
    _order = "code, date_from desc"

    code = fields.Selection(RATE_CODES, string="항목", required=True, index=True)
    date_from = fields.Date(string="적용 시작", required=True)
    date_to = fields.Date(string="적용 종료", help="비우면 무기한")
    employee_rate = fields.Float(string="근로자 요율(%)", digits=(8, 4))
    company_rate = fields.Float(string="회사 요율(%)", digits=(8, 4))
    min_base = fields.Float(string="기준보수 하한(월)", help="0 = 하한 없음")
    max_base = fields.Float(string="기준보수 상한(월)", help="0 = 상한 없음")
    note = fields.Char(string="비고")

    @api.model
    def _proration_factor(self, contract, date_from, date_to):
        """중도입퇴사 일할계산 비율. 정책은 시스템 파라미터
        hr_payroll_kr.proration = calendar(월력일수, 기본) | fixed30(30일 고정) | none(일할 안 함).
        재직일수 = 계약기간과 급여기간의 겹치는 역일수."""
        policy = self.env["ir.config_parameter"].sudo().get_param(
            "hr_payroll_kr.proration", "calendar")
        if policy == "none":
            return 1.0
        start = max(date_from, contract.date_start) if contract.date_start else date_from
        end = min(date_to, contract.date_end) if contract.date_end else date_to
        if end < start:
            return 0.0
        worked = (end - start).days + 1
        month_days = (date_to - date_from).days + 1 if policy == "calendar" else 30
        return min(1.0, worked / month_days)

    @api.model
    def _find(self, code, date):
        return self.search([
            ("code", "=", code), ("date_from", "<=", date),
            "|", ("date_to", "=", False), ("date_to", ">=", date),
        ], order="date_from desc", limit=1)

    @api.model
    def _employee_amount(self, code, base, date):
        """근로자 부담액 = 기준보수(상·하한 적용) × 근로자 요율. 요율 미등록이면 0."""
        rate = self._find(code, date)
        if not rate:
            return 0.0
        capped = base
        if rate.min_base:
            capped = max(capped, rate.min_base)
        if rate.max_base:
            capped = min(capped, rate.max_base)
        return round(capped * rate.employee_rate / 100.0)

    @api.model
    def _company_amount(self, code, base, date):
        rate = self._find(code, date)
        if not rate:
            return 0.0
        capped = base
        if rate.min_base:
            capped = max(capped, rate.min_base)
        if rate.max_base:
            capped = min(capped, rate.max_base)
        return round(capped * rate.company_rate / 100.0)


class KrIncomeTaxBracket(models.Model):
    """근로소득 간이세액표 — 국세청 고시 데이터를 그대로 적재 (native import 지원).
    데이터 미입력 시 소득세 0 계산 (구조 먼저, 데이터 나중 원칙)."""
    _name = "kr.income.tax.bracket"
    _description = "간이세액표"
    _order = "date_from desc, income_from, dependents"

    date_from = fields.Date(string="적용 시작", required=True)
    date_to = fields.Date(string="적용 종료")
    income_from = fields.Float(string="월급여 이상", required=True)
    income_to = fields.Float(string="월급여 미만", required=True)
    dependents = fields.Integer(string="공제대상 가족수(본인 포함)", required=True, default=1)
    tax_amount = fields.Float(string="원천징수 소득세(월)")

    @api.model
    def _lookup(self, income, dependents, date):
        bracket = self.search([
            ("date_from", "<=", date),
            "|", ("date_to", "=", False), ("date_to", ">=", date),
            ("income_from", "<=", income), ("income_to", ">", income),
            ("dependents", "=", max(1, min(dependents, 11))),
        ], order="date_from desc", limit=1)
        return bracket.tax_amount or 0.0
