from odoo import api, fields, models, _


class IatfDrawingIssueRegister(models.Model):
    _name = "iatf.drawing.issue.register"
    _description = "도면불출대장"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "issue_number desc"
    _rec_name = "issue_number"

    issue_number = fields.Char(
        string="불출 번호",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    drawing_number = fields.Char(string="도면 번호", tracking=True)
    drawing_title = fields.Char(string="도면명", tracking=True)
    revision = fields.Char(string="개정")
    issue_date = fields.Date(string="불출일자", default=fields.Date.today)
    issued_by_id = fields.Many2one(
        "res.users",
        string="불출자",
        default=lambda self: self.env.user,
    )
    recipient_id = fields.Many2one("res.partner", string="수령자/고객")
    department_id = fields.Many2one("hr.department", string="부서")
    purpose = fields.Text(string="불출 목적")
    file_link = fields.Char(string="파일 링크")
    document_status_id = fields.Many2one(
        "iatf.drawing.config",
        string="문서상태",
        domain=[("config_type", "=", "document_status")],
        tracking=True,
    )
    note = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("issue_number", _("New")) == _("New"):
                vals["issue_number"] = (
                    self.env["ir.sequence"].next_by_code("iatf.drawing.issue.register")
                    or _("New")
                )
        return super().create(vals_list)
