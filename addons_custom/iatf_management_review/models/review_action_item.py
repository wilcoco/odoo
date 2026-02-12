from odoo import fields, models


class IatfManagementReviewAction(models.Model):
    _name = "iatf.management.review.action"
    _description = "Management Review Action Item"
    _order = "due_date, id"

    review_id = fields.Many2one(
        "iatf.management.review", string="Review", required=True, ondelete="cascade", index=True,
    )
    description = fields.Char(string="Action Item", required=True)
    responsible_id = fields.Many2one("res.users", string="Responsible", required=True)
    due_date = fields.Date(string="Due Date")
    completion_date = fields.Date(string="Completion Date")
    state = fields.Selection(
        [("open", "Open"), ("in_progress", "In Progress"), ("done", "Done")],
        string="Status", default="open",
    )
    notes = fields.Text(string="Notes / Result")

    def action_done(self):
        self.write({"state": "done", "completion_date": fields.Date.today()})
