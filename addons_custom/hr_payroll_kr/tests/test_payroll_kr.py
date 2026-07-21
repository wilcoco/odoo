from datetime import datetime

import pytz

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPayrollKr(TransactionCase):
    """급여 배터리 승격본 — 4대보험 정액·요율 유효기간·일할·상여/OT·고지액 우선·
    퇴직금 손계산·근태 집계→자동 주입→갱신 플래그."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stype = cls.env.ref("hr_payroll_kr.structure_type_kr")
        cls.struct = cls.env.ref("hr_payroll_kr.structure_kr_regular")
        cls.itypes = {r.code: r.id for r in cls.env["hr.payslip.input.type"].search([])}

    def _slip(self, contract, inputs=None, df="2026-07-01", dt="2026-07-31"):
        slip = self.env["hr.payslip"].create({
            "name": "t", "employee_id": contract.employee_id.id, "contract_id": contract.id,
            "struct_id": self.struct.id, "date_from": df, "date_to": dt,
            "input_line_ids": [(0, 0, {"input_type_id": self.itypes[k], "amount": v})
                               for k, v in (inputs or {}).items()]})
        slip.compute_sheet()
        return slip, {l.code: l.total for l in slip.line_ids}

    def _contract(self, name, **vals):
        emp = self.env["hr.employee"].create({"name": name})
        base = {"name": "c", "employee_id": emp.id, "wage": 3000000,
                "structure_type_id": self.stype.id, "date_start": "2026-01-01", "state": "open"}
        base.update(vals)
        return self.env["hr.contract"].create(base)

    def test_insurance_amounts_and_rate_period(self):
        c = self._contract("보험검증")
        # BONUS0 로 상여 격리 — 보험 정액 검증은 기본급 300만 기준
        _, l = self._slip(c, {"BONUS0": 1})
        self.assertEqual(l["KRNP"], -135000, "국민연금 4.5%")
        self.assertEqual(l["KRHI"], -106350, "건강보험 3.545%")
        self.assertAlmostEqual(l["KRLTC"], -13772, delta=2, msg="장기요양 12.95%")
        self.assertEqual(l["KREI"], -27000, "고용보험 0.9%")
        # 새 기간 요율 행 추가만으로 반영 (코드 수정 없음)
        self.env["kr.payroll.rate"].search([("code", "=", "national_pension")]).write(
            {"date_to": "2026-12-31"})
        self.env["kr.payroll.rate"].create({
            "code": "national_pension", "date_from": "2027-01-01",
            "employee_rate": 5.0, "company_rate": 5.0})
        _, l2 = self._slip(c, {"BONUS0": 1}, df="2027-01-01", dt="2027-01-31")
        self.assertEqual(l2["KRNP"], -150000, "2027 요율 자동 반영")

    def test_notice_priority_and_bonus_ot(self):
        c = self._contract("고지검증", kr_wage_type="daily", kr_daily_wage=100000, wage=0)
        self.env["kr.insurance.notice"].create({
            "employee_id": c.employee_id.id, "code": "health",
            "date_from": "2026-07-01", "amount": 120000})
        _, l = self._slip(c, {"DAYS": 26, "CALW": 300000, "OTEXT": 10, "MEAL": 230000})
        self.assertEqual(l["BASIC"], 2600000, "일급제 = 일급×일수")
        self.assertEqual(l["BONUS"], round((2600000 + 300000) * 650 / 1200), "상여 650%/12")
        hourly = (l["BASIC"] + 300000 + l["BONUS"]) / 209
        self.assertAlmostEqual(l["OTEXT"], round(hourly * 15), delta=1, msg="잔업 1.5×10h")
        self.assertEqual(l["KRHI"], -120000, "건보 EDI 고지액 우선")
        self.assertNotIn("KRLTC", l, "고지액엔 장기요양 포함 — 별도 계산 안 함")
        self.assertAlmostEqual(l["TAXBASE"], l["GROSS"] - 200000, delta=1, msg="식대 비과세")

    def test_proration_and_probation(self):
        c = self._contract("일할검증", date_start="2026-07-16")
        _, l = self._slip(c)
        self.assertEqual(l["BASIC"], 1600000, "중도입사 fixed30: 16/30")
        c2 = self._contract("수습검증", kr_is_probation=True)
        _, l2 = self._slip(c2, {"CALW": 300000})
        self.assertEqual(l2["BASIC"], 2700000, "수습 90%")
        self.assertEqual(l2["BONUS"], 0, "수습 상여 0")

    def test_severance_formula(self):
        c = self._contract("퇴직검증", date_start="2024-08-01")
        sev = self.env["kr.severance.estimate"].create({
            "employee_id": c.employee_id.id, "date_leave": "2026-08-01",
            "months3_wage": 9300000, "annual_bonus": 4000000, "annual_leave_pay": 1200000})
        self.assertEqual(sev.service_days, 730)
        avg = round((9300000 + 4000000 * 3 / 12 + 1200000 * 3 / 12) / 92)
        self.assertEqual(sev.avg_daily_wage, avg)
        self.assertEqual(sev.severance_amount, round(avg * 30 * 730 / 365))

    def test_attendance_to_payslip_with_refresh(self):
        c = self._contract("근태검증", kr_wage_type="daily", kr_daily_wage=100000, wage=0)
        emp = c.employee_id
        emp.resource_calendar_id.tz = "Asia/Seoul"
        tz = pytz.timezone("Asia/Seoul")

        def att(d, h1, h2):
            ci = tz.localize(datetime(2026, 7, d, h1, 0)).astimezone(pytz.utc).replace(tzinfo=None)
            co = tz.localize(datetime(2026, 7, d, h2, 0)).astimezone(pytz.utc).replace(tzinfo=None)
            self.env["hr.attendance"].create(
                {"employee_id": emp.id, "check_in": ci, "check_out": co})

        att(6, 8, 19)   # 월: 잔업 2
        att(7, 8, 17)   # 화: 정시
        sheet = self.env["kr.attendance.sheet"].create({
            "employee_id": emp.id, "date_from": "2026-07-01", "date_to": "2026-07-31"})
        sheet.action_aggregate()
        self.assertEqual(sheet.days_worked, 2)
        self.assertEqual(sheet.hours_overtime, 2.0)
        sheet.action_confirm()
        slip, l = self._slip(c)
        codes = {i.input_type_id.code: i for i in slip.input_line_ids}
        self.assertEqual(codes["DAYS"].amount, 2.0, "근태 자동 주입")
        self.assertTrue(codes["OTEXT"].kr_auto_filled)
        # 집계 보정 → 재계산 시 자동 라인 갱신, 수동 전환 라인은 불변
        sheet.action_draft()
        sheet.hours_overtime = 5.0
        sheet.action_confirm()
        slip.compute_sheet()
        self.assertEqual(codes["OTEXT"].amount, 5.0, "집계 수정 반영")
        codes["OTEXT"].write({"amount": 9.0, "kr_auto_filled": False})
        slip.compute_sheet()
        self.assertEqual(codes["OTEXT"].amount, 9.0, "수동 전환 존중")
