from odoo import api, fields, models, _


class IatfPmSchedule(models.Model):
    _name = "iatf.pm.schedule"
    _description = "예방보전(PM) 계획/실적"
    _inherit = ["mail.thread"]
    _order = "planned_date desc"

    name = fields.Char(
        string="PM 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    equipment_id = fields.Many2one("iatf.equipment", string="설비", required=True, tracking=True)
    pm_type = fields.Selection(
        [
            ("daily", "일상 보전"),
            ("weekly", "주간 보전"),
            ("monthly", "월간 보전"),
            ("quarterly", "분기 보전"),
            ("annual", "연간 보전"),
            ("overhaul", "오버홀"),
        ],
        string="PM 유형", required=True, default="monthly",
    )
    planned_date = fields.Date(string="계획일", required=True)
    actual_date = fields.Date(string="실시일")
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user)
    technician = fields.Char(string="작업자")
    duration_hours = fields.Float(string="소요 시간")

    # ── 점검 내용 ──
    checklist = fields.Html(string="점검 항목")
    work_done = fields.Html(string="작업 내용")
    parts_replaced = fields.Text(string="교체 부품")
    result = fields.Selection(
        [("ok", "양호"), ("repair", "수리 필요"), ("replace", "교체 필요")],
        string="결과",
    )

    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [("planned", "계획"), ("done", "완료"), ("cancelled", "취소")],
        string="상태", default="planned", tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.pm.schedule") or _("New")
        return super().create(vals_list)

    def action_done(self):
        for rec in self:
            rec.write({"state": "done", "actual_date": fields.Date.today()})
            rec.equipment_id.write({"last_pm_date": fields.Date.today()})
