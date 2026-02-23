from odoo import api, fields, models, _


class IatfDrawingChangeRegister(models.Model):
    _name = "iatf.drawing.change.register"
    _description = "변경 관리대장(4M, EO) - 고객사"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "change_number desc"
    _rec_name = "change_number"

    change_number = fields.Char(
        string="변경 번호",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    eo_number = fields.Char(string="EO번호", tracking=True)
    change_type_id = fields.Many2one(
        "iatf.drawing.config",
        string="변경 구분(4M+E)",
        domain=[("config_type", "=", "change_type")],
        tracking=True,
    )
    change_item = fields.Char(string="변경 항목")
    part_number = fields.Char(string="품번")
    part_name = fields.Char(string="품명")
    customer_id = fields.Many2one("res.partner", string="고객사")
    request_date = fields.Date(string="요청일자")
    approval_date = fields.Date(string="승인일자")
    completion_date = fields.Date(string="완료일자")
    description = fields.Text(string="변경 내용")
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
            if vals.get("change_number", _("New")) == _("New"):
                vals["change_number"] = (
                    self.env["ir.sequence"].next_by_code("iatf.drawing.change.register")
                    or _("New")
                )
        return super().create(vals_list)
