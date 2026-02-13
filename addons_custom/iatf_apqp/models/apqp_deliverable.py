from odoo import api, fields, models, _


class IatfApqpDeliverable(models.Model):
    _name = "iatf.apqp.deliverable"
    _description = "APQP Phase Deliverable"
    _order = "sequence, id"

    phase_id = fields.Many2one(
        "iatf.apqp.phase", string="단계", required=True, ondelete="cascade", index=True,
    )
    project_id = fields.Many2one(
        "iatf.apqp.project", string="APQP 프로젝트",
        related="phase_id.project_id", store=True, readonly=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="산출물", required=True)
    description = fields.Text(string="설명")
    is_required = fields.Boolean(string="필수", default=True)

    responsible_id = fields.Many2one("res.users", string="담당자")
    due_date = fields.Date(string="기한")
    completion_date = fields.Date(string="완료일")

    state = fields.Selection(
        [
            ("todo", "할 일"),
            ("in_progress", "진행 중"),
            ("done", "완료"),
            ("na", "해당없음"),
        ],
        string="상태", default="todo",
    )

    document_id = fields.Many2one("iatf.document", string="연결 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    def action_done(self):
        self.write({"state": "done", "completion_date": fields.Date.today()})

    def action_na(self):
        self.write({"state": "na"})

    def action_reset(self):
        self.write({"state": "todo", "completion_date": False})
