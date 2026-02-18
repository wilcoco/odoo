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
    task_id = fields.Many2one("project.task", string="프로젝트 태스크", copy=False)
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    def action_done(self):
        self.write({"state": "done", "completion_date": fields.Date.today()})
        for rec in self:
            if rec.task_id and rec.task_id.stage_id:
                done_stage = self.env["project.task.type"].search([
                    ("project_ids", "in", rec.task_id.project_id.id),
                    ("fold", "=", True),
                ], limit=1)
                if done_stage:
                    rec.task_id.stage_id = done_stage.id

    def action_na(self):
        self.write({"state": "na"})

    def action_reset(self):
        self.write({"state": "todo", "completion_date": False})

    def action_create_task(self):
        """산출물 → 프로젝트 태스크 자동 생성 (B7)"""
        self.ensure_one()
        if self.task_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "project.task",
                "res_id": self.task_id.id,
                "view_mode": "form",
                "target": "current",
            }
        # APQP 프로젝트에 연결된 project.project 찾기
        proj = self.project_id
        odoo_project = False
        if hasattr(proj, "project_project_id") and proj.project_project_id:
            odoo_project = proj.project_project_id
        if not odoo_project:
            odoo_project = self.env["project.project"].search([
                ("name", "ilike", proj.title or proj.name),
            ], limit=1)
        if not odoo_project:
            odoo_project = self.env["project.project"].create({
                "name": _("APQP: %s") % (proj.title or proj.name),
            })
            proj.project_project_id = odoo_project.id if hasattr(proj, "project_project_id") else False

        task = self.env["project.task"].create({
            "name": _("[%s] %s") % (self.phase_id.name, self.name),
            "project_id": odoo_project.id,
            "user_ids": [(6, 0, [self.responsible_id.id])] if self.responsible_id else [],
            "date_deadline": self.due_date,
            "description": self.description or "",
        })
        self.task_id = task.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "project.task",
            "res_id": task.id,
            "view_mode": "form",
            "target": "current",
        }
