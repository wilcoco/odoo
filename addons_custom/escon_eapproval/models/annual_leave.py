"""연차 자동 발생 엔진 — 에스콘 연차 규정(그룹웨어 gw.goescon.com 과 동일) 구현.

규정 (입사일 기준):
- 입사 첫해: 매월(입사일 응당일) 1일씩 발생, 최대 11일
- 입사 1년 후: 기념일에 15일 발생
- 입사 3년 이상: 기념일에 16일 발생
- 미사용 연차는 다음 해로 이월되지 않음

Odoo 표준 적립 플랜(hr.leave.accrual.plan)의 연 단위 발생은 고정 달력일 기준이라
입사 기념일 기준 발생/소멸을 표현할 수 없어, 매일 도는 크론이 유효기간이 있는
배정(hr.leave.allocation)을 직접 생성/갱신한다.

- 첫해 배정 1건: date_from=입사일, date_to=1주년 전날, 일수는 경과 개월수(최대 11)로 증가
- 이후 연차별 배정 1건씩: date_from=k주년, date_to=(k+1)주년 전날, 15일(근속 3년 이상 16일)
- 배정 유효기간이 지나면 Odoo 가 잔여를 자동으로 소멸 처리(이월 없음)
- 멱등: 같은 날 여러 번 실행해도 결과 동일. 관리자가 일수를 수동으로 늘린 배정은 줄이지 않음
"""

import logging

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

FIRST_YEAR_MAX = 11
BASE_DAYS = 15
SENIOR_DAYS = 16
SENIOR_YEARS = 3


class EsconAnnualLeave(models.AbstractModel):
    _name = "escon.annual.leave"
    _description = "연차 자동 발생 (에스콘 규정)"

    @api.model
    def _leave_type(self):
        return self.env.ref("escon_eapproval.leave_type_annual", raise_if_not_found=False)

    @api.model
    def _hire_date(self, employee):
        """입사일: 직접 입력(eap_hire_date) 우선, 없으면 첫 계약 시작일."""
        return employee.eap_hire_date or employee.first_contract_date

    @api.model
    def _entitlement(self, service_years):
        return SENIOR_DAYS if service_years >= SENIOR_YEARS else BASE_DAYS

    @api.model
    def _ensure_allocation(self, employee, leave_type, name, date_from, date_to, days,
                           allow_increase=False):
        """(employee, type, date_from) 를 키로 배정 1건을 보장. 반환: 'created'/'updated'/None."""
        Allocation = self.env["hr.leave.allocation"].sudo()
        alloc = Allocation.with_context(active_test=False).search([
            ("employee_id", "=", employee.id),
            ("holiday_status_id", "=", leave_type.id),
            ("date_from", "=", date_from),
        ], limit=1)
        if not alloc:
            alloc = Allocation.create({
                "name": name,
                "employee_id": employee.id,
                "holiday_status_id": leave_type.id,
                "allocation_type": "regular",
                "number_of_days": days,
                "date_from": date_from,
                "date_to": date_to,
                "notes": "에스콘 연차 규정 자동 발생 (escon.annual.leave)",
            })
            if alloc.state != "validate":
                alloc.action_validate()
            return "created"
        # 첫해 배정: 개월수 증가분만 반영. 수동으로 더 크게 준 배정은 건드리지 않는다.
        if allow_increase and alloc.number_of_days < days:
            alloc.write({"number_of_days": days})
            if alloc.state != "validate":
                alloc.action_validate()
            return "updated"
        return None

    @api.model
    def update_annual_allocations(self, employees=None, today=None):
        """전 직원(또는 지정 직원) 연차 배정 갱신. 요약 dict 반환."""
        leave_type = self._leave_type()
        summary = {"created": [], "updated": [], "no_hire_date": []}
        if not leave_type:
            _logger.warning("연차 휴가 유형(leave_type_annual)이 없어 연차 발생을 건너뜁니다.")
            return summary
        today = today or fields.Date.context_today(self)
        if employees is None:
            employees = self.env["hr.employee"].search([("active", "=", True)])

        for emp in employees:
            hire = self._hire_date(emp)
            if not hire or hire > today:
                summary["no_hire_date"].append(emp.name)
                continue
            service = relativedelta(today, hire)
            if service.years < 1:
                # 입사 첫해: 경과한 만 개월수만큼 (최대 11)
                months = min(service.years * 12 + service.months, FIRST_YEAR_MAX)
                if months <= 0:
                    continue
                result = self._ensure_allocation(
                    emp, leave_type,
                    "연차 (입사 첫해)",
                    hire, hire + relativedelta(years=1, days=-1),
                    months, allow_increase=True,
                )
            else:
                k = service.years
                start = hire + relativedelta(years=k)
                result = self._ensure_allocation(
                    emp, leave_type,
                    "연차 %s년 (근속 %d년)" % (start.year, k),
                    start, hire + relativedelta(years=k + 1, days=-1),
                    self._entitlement(k),
                )
            if result == "created":
                summary["created"].append(emp.name)
            elif result == "updated":
                summary["updated"].append(emp.name)

        if summary["created"] or summary["updated"]:
            _logger.info("연차 발생: 신규 %s건 %s / 갱신 %s건 %s",
                         len(summary["created"]), summary["created"],
                         len(summary["updated"]), summary["updated"])
        if summary["no_hire_date"]:
            _logger.warning("입사일 미입력으로 연차 발생 제외: %s", summary["no_hire_date"])
        return summary

    @api.model
    def _cron_update_annual_leave(self):
        self.update_annual_allocations()
        return True

    @api.model
    def action_update_now(self):
        """설정 메뉴의 '연차 배정 지금 갱신' — 실행 후 결과 알림."""
        summary = self.update_annual_allocations()
        message = "신규 배정 %d건, 갱신 %d건." % (
            len(summary["created"]), len(summary["updated"]))
        if summary["no_hire_date"]:
            message += " 입사일 미입력 제외: %s" % ", ".join(summary["no_hire_date"])
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "연차 배정 갱신 완료",
                "message": message,
                "type": "success" if not summary["no_hire_date"] else "warning",
                "sticky": bool(summary["no_hire_date"]),
            },
        }


class HrEmployeeHire(models.Model):
    _inherit = "hr.employee"

    eap_hire_date = fields.Date(
        string="입사일", tracking=True,
        help="연차 자동 발생 기준일. 비워 두면 첫 계약 시작일을 사용합니다.")
