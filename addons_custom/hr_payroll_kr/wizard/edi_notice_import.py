import base64
import csv
import io

from odoo import fields, models, _
from odoo.exceptions import UserError

# EDI 고지내역서 일괄 반영 골격 — 잠정 표준 컬럼:
#   employee(사번 또는 성명), code(health/national_pension 또는 건강/연금), date_from(YYYY-MM-01), amount
# 공단 EDI 실물 파일 양식을 받으면 _normalize_row 만 그 양식에 맞게 조정한다.
CODE_ALIASES = {
    "health": "health", "건강": "health", "건강보험": "health",
    "national_pension": "national_pension", "연금": "national_pension", "국민연금": "national_pension",
}


class KrEdiNoticeImport(models.TransientModel):
    _name = "kr.edi.notice.import"
    _description = "EDI 고지내역 일괄 업로드"

    file = fields.Binary(string="고지내역 CSV", required=True)
    filename = fields.Char()
    result = fields.Text(string="처리 결과", readonly=True)

    def _normalize_row(self, row):
        """행 → (직원식별자, 보험코드, 적용시작일, 금액). 실물 EDI 양식 확정 시 이 함수만 수정."""
        emp_key = (row.get("employee") or row.get("사번") or row.get("성명") or "").strip()
        code = CODE_ALIASES.get((row.get("code") or row.get("보험") or "").strip())
        date_from = (row.get("date_from") or row.get("적용월") or "").strip()
        if len(date_from) == 7:  # YYYY-MM → 월초일
            date_from += "-01"
        amount = float(row.get("amount") or row.get("고지액") or 0)
        return emp_key, code, date_from, amount

    def action_import(self):
        self.ensure_one()
        try:
            raw = base64.b64decode(self.file).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise UserError(_("UTF-8 CSV 파일만 지원합니다."))
        Employee = self.env["hr.employee"]
        Notice = self.env["kr.insurance.notice"]
        created, updated, errors = 0, 0, []
        for i, row in enumerate(csv.DictReader(io.StringIO(raw)), start=2):
            if not any((v or "").strip() for v in row.values()):
                continue
            emp_key, code, date_from, amount = self._normalize_row(row)
            if not (emp_key and code and date_from and amount):
                errors.append(_("%d행: 필수값 누락/식별 불가 (%s)") % (i, dict(row)))
                continue
            emp = Employee.search(["|", ("barcode", "=", emp_key), ("name", "=", emp_key)])
            if len(emp) != 1:
                errors.append(_("%d행: 직원 '%s' %s") % (
                    i, emp_key, _("없음") if not emp else _("동명 %d명 — 사번 사용 필요") % len(emp)))
                continue
            # 멱등: 같은 직원·보험·시작일이면 금액 갱신
            existing = Notice.search([("employee_id", "=", emp.id), ("code", "=", code),
                                      ("date_from", "=", date_from)], limit=1)
            if existing:
                existing.write({"amount": amount})
                updated += 1
            else:
                Notice.create({"employee_id": emp.id, "code": code,
                               "date_from": date_from, "amount": amount,
                               "note": self.filename or "EDI 업로드"})
                created += 1
        self.result = _("신규 %(c)d건 · 갱신 %(u)d건 · 오류 %(e)d건\n%(err)s") % {
            "c": created, "u": updated, "e": len(errors), "err": "\n".join(errors[:20])}
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new", "name": _("EDI 고지내역 업로드")}
