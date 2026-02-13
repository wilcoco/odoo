from odoo import fields, models


class IatfPpapElement(models.Model):
    _name = "iatf.ppap.element"
    _description = "PPAP Element"
    _order = "element_number_int, id"

    submission_id = fields.Many2one(
        "iatf.ppap.submission", string="PPAP 제출", required=True, ondelete="cascade", index=True,
    )
    element_number = fields.Char(string="요소 #", required=True)
    element_number_int = fields.Integer(compute="_compute_number_int", store=True)
    name = fields.Char(string="요소명", required=True)
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

    def _compute_number_int(self):
        for rec in self:
            try:
                rec.element_number_int = int(rec.element_number)
            except (ValueError, TypeError):
                rec.element_number_int = 0

    def action_done(self):
        self.write({"state": "done", "completion_date": fields.Date.today()})

    def action_na(self):
        self.write({"state": "na"})
