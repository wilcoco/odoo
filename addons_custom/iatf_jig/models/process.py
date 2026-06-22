from odoo import fields, models


class IatfProcess(models.Model):
    _name = "iatf.process"
    _description = "공정(Process) 마스터"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "code"

    code = fields.Char(string="공정 코드", required=True, copy=False, tracking=True)
    name = fields.Char(string="공정명", required=True, tracking=True)
    category = fields.Selection(
        [("quality", "품질"), ("production", "생산"), ("purchase", "구매"),
         ("development", "개발"), ("other", "기타")],
        string="분류", tracking=True,
    )
    document_no = fields.Char(string="문서 번호")
    revision = fields.Char(string="개정")
    effective_date = fields.Date(string="시행일")
    owner_dept_id = fields.Many2one("hr.department", string="주관 부서")
    description = fields.Text(string="설명")
    active = fields.Boolean(string="활성", default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
