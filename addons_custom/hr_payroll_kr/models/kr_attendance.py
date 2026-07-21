from datetime import datetime, timedelta, time

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# 매뉴얼 1장(근태 확인) 뼈대: 오두 표준 출퇴근(hr.attendance)을 정본으로
# 월 근태 집계를 만들고, 급여명세서 계산 시 시간 입력(DAYS/OTEXT/OTHOL/OTHOLX/
# OTNIGHT/LATE)을 자동 주입한다. 분류 규칙:
#   평일(소정근로 있는 날): 소정 초과분=잔업, 미달분=지각/조퇴
#   휴일(소정근로 없는 날·전사휴일): 8h 이내=특근, 초과=특잔
#   심야: 22:00~05:00 겹치는 시간(가산)
# 자동 집계값은 담당자가 라인에서 보정 가능 — 확정된 집계만 급여에 반영.


class KrAttendanceSheet(models.Model):
    _name = "kr.attendance.sheet"
    _description = "월 근태 집계"
    _inherit = ["mail.thread"]
    _order = "date_from desc, employee_id"

    employee_id = fields.Many2one("hr.employee", string="직원", required=True, tracking=True)
    date_from = fields.Date(string="시작", required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string="종료", required=True)
    line_ids = fields.One2many("kr.attendance.sheet.line", "sheet_id", string="일별 내역")
    days_worked = fields.Float(string="근무일수", tracking=True)
    hours_overtime = fields.Float(string="잔업시간")
    hours_holiday = fields.Float(string="특근시간")
    hours_holiday_ot = fields.Float(string="특잔시간")
    hours_night = fields.Float(string="심야시간")
    hours_late = fields.Float(string="지각/조퇴시간")
    warning_52h = fields.Text(string="주52시간 경고", readonly=True,
                              help="주간 실근로 52시간 초과 주 목록 (매뉴얼 1-3)")
    state = fields.Selection([("draft", "초안"), ("confirmed", "확정")],
                             default="draft", tracking=True,
                             help="확정된 집계만 급여명세서에 자동 반영")
    note = fields.Text(string="특이사항")

    _sql_constraints = [("emp_period_uniq", "unique(employee_id, date_from, date_to)",
                         "같은 직원·기간의 근태 집계가 이미 있습니다.")]

    def _tz(self):
        override = self.env["ir.config_parameter"].sudo().get_param("hr_payroll_kr.attendance_tz")
        if override:
            return pytz.timezone(override)
        cal = self.employee_id.resource_calendar_id
        return pytz.timezone(cal.tz or self.env.user.tz or "Asia/Seoul")

    def _planned_hours(self, day):
        """해당 날짜의 소정근로시간 (전사휴일이면 0)."""
        cal = self.employee_id.resource_calendar_id
        if not cal:
            return 8.0 if day.weekday() < 5 else 0.0
        leaves = self.env["resource.calendar.leaves"].search_count([
            ("calendar_id", "in", (False, cal.id)), ("resource_id", "=", False),
            ("date_from", "<=", datetime.combine(day, time.max)),
            ("date_to", ">=", datetime.combine(day, time.min)),
        ])
        if leaves:
            return 0.0
        return sum(a.hour_to - a.hour_from for a in cal.attendance_ids
                   if int(a.dayofweek) == day.weekday()
                   and a.day_period != "lunch")

    @staticmethod
    def _night_overlap(start, end):
        """[start, end](로컬 naive) 와 22:00~익일 05:00 의 겹침 시간."""
        total = 0.0
        day = start.date() - timedelta(days=1)
        while day <= end.date():
            for win_start, win_end in (
                    (datetime.combine(day, time(22, 0)),
                     datetime.combine(day + timedelta(days=1), time(5, 0))),):
                s, e = max(start, win_start), min(end, win_end)
                if e > s:
                    total += (e - s).total_seconds() / 3600.0
            day += timedelta(days=1)
        return total

    def action_aggregate(self):
        """출퇴근 기록(hr.attendance)에서 일별 분류·집계 생성."""
        Line = self.env["kr.attendance.sheet.line"]
        lunch = float(self.env["ir.config_parameter"].sudo().get_param(
            "hr_payroll_kr.lunch_break_hours", "1.0"))
        for sheet in self:
            if sheet.state != "draft":
                raise UserError(_("초안 상태에서만 재집계할 수 있습니다."))
            sheet.line_ids.unlink()
            tz = sheet._tz()
            atts = self.env["hr.attendance"].search([
                ("employee_id", "=", sheet.employee_id.id),
                ("check_in", ">=", datetime.combine(sheet.date_from, time.min) - timedelta(hours=12)),
                ("check_in", "<=", datetime.combine(sheet.date_to, time.max)),
                ("check_out", "!=", False),
            ])
            by_day = {}
            for att in atts:
                ci = pytz.utc.localize(att.check_in).astimezone(tz).replace(tzinfo=None)
                co = pytz.utc.localize(att.check_out).astimezone(tz).replace(tzinfo=None)
                if not (sheet.date_from <= ci.date() <= sheet.date_to):
                    continue
                d = by_day.setdefault(ci.date(), {"worked": 0.0, "night": 0.0})
                raw = (co - ci).total_seconds() / 3600.0
                d["worked"] += raw
                d["night"] += self._night_overlap(ci, co)
            totals = {"days": 0.0, "ot": 0.0, "hol": 0.0, "holx": 0.0, "night": 0.0, "late": 0.0}
            weekly = {}
            for day in sorted(by_day):
                d = by_day[day]
                worked = d["worked"] - (lunch if d["worked"] > 6 else 0.0)
                planned = sheet._planned_hours(day)
                vals = {"sheet_id": sheet.id, "date": day, "worked_hours": worked,
                        "planned_hours": planned, "night_hours": d["night"]}
                if planned:
                    vals["overtime_hours"] = max(0.0, worked - planned)
                    vals["late_hours"] = max(0.0, planned - worked)
                    totals["days"] += 1
                    totals["ot"] += vals["overtime_hours"]
                    totals["late"] += vals["late_hours"]
                else:
                    vals["holiday_hours"] = min(worked, 8.0)
                    vals["holiday_ot_hours"] = max(0.0, worked - 8.0)
                    totals["hol"] += vals["holiday_hours"]
                    totals["holx"] += vals["holiday_ot_hours"]
                totals["night"] += d["night"]
                Line.create(vals)
                week = day.isocalendar()[:2]
                weekly[week] = weekly.get(week, 0.0) + worked
            over = ["%d년 %d주차: %.1fh" % (y, w, h) for (y, w), h in sorted(weekly.items()) if h > 52.0]
            sheet.write({
                "days_worked": totals["days"], "hours_overtime": totals["ot"],
                "hours_holiday": totals["hol"], "hours_holiday_ot": totals["holx"],
                "hours_night": totals["night"], "hours_late": totals["late"],
                "warning_52h": ("⚠️ 주 52시간 초과:\n" + "\n".join(over)) if over else False,
            })
        return True

    def action_confirm(self):
        for sheet in self:
            if not sheet.line_ids and not sheet.days_worked:
                raise UserError(_("집계 내역이 없습니다. '출퇴근에서 집계' 후 확정하세요."))
            sheet.state = "confirmed"

    def action_draft(self):
        self.write({"state": "draft"})


class KrAttendanceSheetLine(models.Model):
    _name = "kr.attendance.sheet.line"
    _description = "월 근태 집계 일별 내역"
    _order = "date"

    sheet_id = fields.Many2one("kr.attendance.sheet", required=True, ondelete="cascade")
    date = fields.Date(string="일자", required=True)
    planned_hours = fields.Float(string="소정")
    worked_hours = fields.Float(string="실근로")
    overtime_hours = fields.Float(string="잔업")
    holiday_hours = fields.Float(string="특근")
    holiday_ot_hours = fields.Float(string="특잔")
    night_hours = fields.Float(string="심야")
    late_hours = fields.Float(string="지각/조퇴")
    note = fields.Char(string="비고")


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    kr_attendance_sheet_id = fields.Many2one(
        "kr.attendance.sheet", string="근태 집계", readonly=True, copy=False,
        help="계산 시 자동 연결된 확정 근태 집계")

    def compute_sheet(self):
        self._kr_fill_inputs_from_attendance()
        return super().compute_sheet()

    def _kr_fill_inputs_from_attendance(self):
        """확정 근태 집계 → 시간 입력 자동 주입. 이미 수동 입력된 항목은 존중."""
        InputType = self.env["hr.payslip.input.type"]
        for slip in self:
            sheet = self.env["kr.attendance.sheet"].search([
                ("employee_id", "=", slip.employee_id.id), ("state", "=", "confirmed"),
                ("date_from", "<=", slip.date_from), ("date_to", ">=", slip.date_to),
            ], limit=1)
            if not sheet:
                continue
            slip.kr_attendance_sheet_id = sheet
            mapping = {
                "DAYS": sheet.days_worked, "OTEXT": sheet.hours_overtime,
                "OTHOL": sheet.hours_holiday, "OTHOLX": sheet.hours_holiday_ot,
                "OTNIGHT": sheet.hours_night, "LATE": sheet.hours_late,
            }
            existing = set(slip.input_line_ids.mapped("input_type_id.code"))
            lines = []
            for code, amount in mapping.items():
                if amount and code not in existing:
                    itype = InputType.search([("code", "=", code)], limit=1)
                    if itype:
                        lines.append((0, 0, {"input_type_id": itype.id, "amount": amount}))
            if lines:
                slip.write({"input_line_ids": lines})
