from odoo import api, fields, models, _


class IatfDrawingProcedure(models.Model):
    _name = "iatf.drawing.procedure"
    _description = "도면관리절차서"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "procedure_number desc"
    _rec_name = "procedure_number"

    procedure_number = fields.Char(
        string="문서 번호",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    name = fields.Char(string="문서명", required=True, tracking=True)
    revision = fields.Char(string="개정", tracking=True)
    effective_date = fields.Date(string="적용일", default=fields.Date.today)
    owner_id = fields.Many2one(
        "res.users",
        string="담당자",
        default=lambda self: self.env.user,
    )
    department_id = fields.Many2one("hr.department", string="부서")
    summary = fields.Text(string="절차 개요")
    file_link = fields.Char(string="절차서 링크")
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
            if vals.get("procedure_number", _("New")) == _("New"):
                vals["procedure_number"] = (
                    self.env["ir.sequence"].next_by_code("iatf.drawing.procedure")
                    or _("New")
                )
        return super().create(vals_list)
