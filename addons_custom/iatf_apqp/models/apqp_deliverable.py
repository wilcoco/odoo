from odoo import api, fields, models, _


class IatfApqpDeliverable(models.Model):
    _name = "iatf.apqp.deliverable"
    _description = "APQP Phase Deliverable"
    _order = "sequence, id"

    phase_id = fields.Many2one(
        "iatf.apqp.phase", string="Phase", required=True, ondelete="cascade", index=True,
    )
    project_id = fields.Many2one(
        "iatf.apqp.project", string="APQP Project",
        related="phase_id.project_id", store=True, readonly=True,
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Deliverable", required=True)
    description = fields.Text(string="Description")
    is_required = fields.Boolean(string="Required", default=True)

    responsible_id = fields.Many2one("res.users", string="Responsible")
    due_date = fields.Date(string="Due Date")
    completion_date = fields.Date(string="Completion Date")

    state = fields.Selection(
        [
            ("todo", "To Do"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("na", "N/A"),
        ],
        string="Status", default="todo",
    )

    document_id = fields.Many2one("iatf.document", string="Linked Document")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")
    notes = fields.Text(string="Notes")

    def action_done(self):
        self.write({"state": "done", "completion_date": fields.Date.today()})

    def action_na(self):
        self.write({"state": "na"})

    def action_reset(self):
        self.write({"state": "todo", "completion_date": False})
