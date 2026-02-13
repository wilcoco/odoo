from odoo import fields, models


class IatfManagementReviewAction(models.Model):
    _name = "iatf.management.review.action"
    _description = "Management Review Action Item"
    _order = "due_date, id"

    review_id = fields.Many2one(
        "iatf.management.review", string="검토", required=True, ondelete="cascade", index=True,
    )
    description = fields.Char(string="조치 항목", required=True)
    responsible_id = fields.Many2one("res.users", string="담당자", required=True)
    due_date = fields.Date(string="기한")
    completion_date = fields.Date(string="완료일")
    state = fields.Selection(
        [("open", "미결"), ("in_progress", "진행 중"), ("done", "완료")],
        string="상태", default="open",
    )
    notes = fields.Text(string="비고 / 결과")

    def action_done(self):
        self.write({"state": "done", "completion_date": fields.Date.today()})
