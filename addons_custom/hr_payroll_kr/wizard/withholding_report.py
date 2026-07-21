from odoo import fields, models, _

# 원천세 신고 집계 골격 — 홈택스 원천징수이행상황신고서(간이세액 A01)에 옮겨 적을
# 월 집계값을 확정 급여명세서에서 산출한다. 신고·납부 자체는 홈택스에서 수기.


class KrWithholdingReport(models.TransientModel):
    _name = "kr.withholding.report"
    _description = "원천세 신고 집계 (원천징수이행상황신고서용)"

    date_from = fields.Date(string="귀속 시작", required=True,
                            default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string="귀속 종료", required=True)
    employee_count = fields.Integer(string="인원", readonly=True)
    total_gross = fields.Float(string="총지급액", readonly=True)
    total_taxable = fields.Float(string="과세 지급액(비과세 제외)", readonly=True)
    income_tax = fields.Float(string="소득세 징수액", readonly=True)
    local_tax = fields.Float(string="지방소득세 징수액", readonly=True)
    note = fields.Text(string="안내", readonly=True,
                       default="확정(완료) 급여명세서 기준 집계입니다. 홈택스 원천징수이행상황신고서 "
                               "'간이세액(A01)' 란에 인원·총지급액(과세)·소득세를 옮겨 적으세요. "
                               "지방소득세는 위택스 신고분입니다.")

    def action_compute(self):
        self.ensure_one()
        slips = self.env["hr.payslip"].search([
            ("state", "in", ("done", "paid")),
            ("date_from", ">=", self.date_from), ("date_to", "<=", self.date_to),
        ])
        totals = {"GROSS": 0.0, "TAXBASE": 0.0, "KRTAX": 0.0, "KRLOCTAX": 0.0}
        for line in slips.line_ids:
            if line.code in totals:
                totals[line.code] += line.total
        self.write({
            "employee_count": len(slips.mapped("employee_id")),
            "total_gross": totals["GROSS"],
            "total_taxable": totals["TAXBASE"],
            "income_tax": -totals["KRTAX"],
            "local_tax": -totals["KRLOCTAX"],
        })
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new", "name": _("원천세 신고 집계")}
