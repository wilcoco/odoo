from odoo import fields, models


class IatfPpapElement(models.Model):
    _name = "iatf.ppap.element"
    _description = "PPAP Element"
    _order = "element_number_int, id"

    submission_id = fields.Many2one(
        "iatf.ppap.submission", string="PPAP Submission", required=True, ondelete="cascade", index=True,
    )
    element_number = fields.Char(string="Element #", required=True)
    element_number_int = fields.Integer(compute="_compute_number_int", store=True)
    name = fields.Char(string="Element Name", required=True)
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
