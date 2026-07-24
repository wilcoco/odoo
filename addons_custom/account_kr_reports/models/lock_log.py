from odoo import fields, models

# 리포트 #34: 마감 잠금 변경 이력 — 잠금 레벨 설정 자체는 표준 설정을 쓰되,
# 완화/해제가 흔적 없이 이뤄지지 않도록 변경을 불변 로그로 남긴다.
LOCK_FIELDS = ("fiscalyear_lock_date", "tax_lock_date", "sale_lock_date",
               "purchase_lock_date", "hard_lock_date", "period_lock_date")


class ResCompany(models.Model):
    _inherit = "res.company"

    def write(self, vals):
        tracked = [f for f in LOCK_FIELDS if f in vals and f in self._fields]
        logs = []
        if tracked:
            for company in self:
                for f in tracked:
                    old = company[f]
                    new = vals[f] or False
                    if str(old or "") == str(new or ""):
                        continue
                    if not new:
                        direction = "release"
                    elif not old or fields.Date.to_date(new) > old:
                        direction = "tighten"
                    else:
                        direction = "loosen"
                    logs.append({
                        "company_id": company.id,
                        "field_name": f,
                        "field_label": self._fields[f].string,
                        "old_date": old,
                        "new_date": new or False,
                        "direction": direction,
                    })
        res = super().write(vals)
        if logs:
            self.env["kr.lock.log"].sudo().create(logs)
        return res


class KrLockLog(models.Model):
    _name = "kr.lock.log"
    _description = "마감 잠금 변경 이력"
    _order = "create_date desc, id desc"

    company_id = fields.Many2one("res.company", string="회사", readonly=True)
    user_id = fields.Many2one("res.users", string="변경자", readonly=True,
                              default=lambda self: self.env.user)
    field_name = fields.Char(string="잠금 필드", readonly=True)
    field_label = fields.Char(string="잠금 종류", readonly=True)
    old_date = fields.Date(string="변경 전", readonly=True)
    new_date = fields.Date(string="변경 후", readonly=True)
    direction = fields.Selection(
        [("tighten", "강화"), ("loosen", "완화"), ("release", "해제")],
        string="구분", readonly=True)
