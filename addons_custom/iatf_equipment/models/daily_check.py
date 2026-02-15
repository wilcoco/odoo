from odoo import api, fields, models, _


class IatfDailyCheck(models.Model):
    _name = "iatf.daily.check"
    _description = "설비 일상점검"
    _order = "check_date desc, equipment_id"

    name = fields.Char(
        string="점검 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    equipment_id = fields.Many2one("iatf.equipment", string="설비", required=True, index=True)
    check_date = fields.Date(string="점검일", default=fields.Date.today, required=True)
    shift = fields.Selection(
        [("day", "주간"), ("evening", "야간"), ("night", "심야")],
        string="근무조", default="day",
    )
    checker_id = fields.Many2one("res.users", string="점검자",
                                  default=lambda self: self.env.user)

    line_ids = fields.One2many("iatf.daily.check.line", "check_id", string="점검 항목")

    overall_result = fields.Selection(
        [("ok", "양호"), ("issue", "이상 있음")],
        string="종합 판정", compute="_compute_overall", store=True,
    )
    notes = fields.Text(string="비고")

    @api.depends("line_ids.result")
    def _compute_overall(self):
        for rec in self:
            if any(l.result == "ng" for l in rec.line_ids):
                rec.overall_result = "issue"
            else:
                rec.overall_result = "ok"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.daily.check") or _("New")
        return super().create(vals_list)


class IatfDailyCheckLine(models.Model):
    _name = "iatf.daily.check.line"
    _description = "일상점검 항목"
    _order = "sequence"

    check_id = fields.Many2one("iatf.daily.check", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    item_name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="기준")
    result = fields.Selection(
        [("ok", "양호"), ("ng", "불량"), ("na", "해당없음")],
        string="결과", default="ok",
    )
    remark = fields.Char(string="비고")
