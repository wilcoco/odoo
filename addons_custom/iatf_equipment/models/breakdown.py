from odoo import api, fields, models, _


class IatfEquipmentBreakdown(models.Model):
    _name = "iatf.equipment.breakdown"
    _description = "설비 고장 이력"
    _inherit = ["mail.thread"]
    _order = "occurrence_date desc"

    name = fields.Char(
        string="고장 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    equipment_id = fields.Many2one("iatf.equipment", string="설비", required=True, tracking=True)
    occurrence_date = fields.Datetime(string="발생 일시", required=True, default=fields.Datetime.now)
    repair_start = fields.Datetime(string="수리 시작")
    repair_end = fields.Datetime(string="수리 완료")
    downtime_hours = fields.Float(string="정지 시간 (hr)", compute="_compute_downtime", store=True)

    breakdown_type = fields.Selection(
        [
            ("mechanical", "기계적 고장"),
            ("electrical", "전기적 고장"),
            ("hydraulic", "유압 고장"),
            ("pneumatic", "공압 고장"),
            ("software", "소프트웨어"),
            ("operator", "조작 실수"),
            ("other", "기타"),
        ],
        string="고장 유형", required=True, default="mechanical",
    )
    severity = fields.Selection(
        [("minor", "경미"), ("major", "중대"), ("critical", "치명")],
        string="심각도", default="major",
    )

    # ── 분석 ──
    symptom = fields.Text(string="고장 증상")
    root_cause = fields.Text(string="원인 분석")
    repair_action = fields.Html(string="수리 내용")
    parts_used = fields.Text(string="사용 부품")
    preventive_action = fields.Html(string="재발 방지 대책")

    responsible_id = fields.Many2one("res.users", string="담당자")
    technician = fields.Char(string="수리 작업자")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [("open", "발생"), ("repairing", "수리 중"), ("closed", "완료")],
        string="상태", default="open", tracking=True,
    )

    @api.depends("occurrence_date", "repair_end")
    def _compute_downtime(self):
        for rec in self:
            if rec.occurrence_date and rec.repair_end:
                delta = rec.repair_end - rec.occurrence_date
                rec.downtime_hours = delta.total_seconds() / 3600.0
            else:
                rec.downtime_hours = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.equipment.breakdown") or _("New")
        return super().create(vals_list)

    def action_start_repair(self):
        self.write({"state": "repairing", "repair_start": fields.Datetime.now()})
        self.mapped("equipment_id").action_breakdown()

    def action_close(self):
        self.write({"state": "closed", "repair_end": fields.Datetime.now()})
        self.mapped("equipment_id").action_activate()
