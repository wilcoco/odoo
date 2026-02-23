from odoo import api, fields, models, _


class IatfDrawingSpecChange(models.Model):
    _name = "iatf.drawing.spec.change"
    _description = "기술사양변경 내역서"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "eo_number desc"
    _rec_name = "eo_number"

    eo_number = fields.Char(
        string="EO번호",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
    )
    product_group_id = fields.Many2one(
        "iatf.drawing.config",
        string="제품군",
        domain=[("config_type", "=", "product_group")],
        tracking=True,
    )
    drawing_type_id = fields.Many2one(
        "iatf.drawing.config",
        string="도면구분",
        domain=[("config_type", "=", "drawing_type")],
        tracking=True,
    )
    product_standard_id = fields.Many2one(
        "iatf.drawing.config",
        string="제품기준",
        domain=[("config_type", "=", "product_standard")],
        tracking=True,
    )
    category_item_id = fields.Many2one(
        "iatf.drawing.config",
        string="구분항목",
        domain=[("config_type", "=", "category_item")],
        tracking=True,
    )
    part_number = fields.Char(string="품번", tracking=True)
    part_name = fields.Char(string="품명", tracking=True)
    car_model_id = fields.Many2one(
        "iatf.drawing.config",
        string="차종",
        domain=[("config_type", "=", "car_model")],
    )
    revision = fields.Char(string="Revision")
    customer_received_date = fields.Date(string="고객접수일자")
    distributor_id = fields.Many2one(
        "res.users",
        string="배포자",
        default=lambda self: self.env.user,
    )
    retention_year_id = fields.Many2one(
        "iatf.drawing.config",
        string="보존년한",
        domain=[("config_type", "=", "retention_year")],
    )
    specification_id = fields.Many2one(
        "iatf.drawing.config",
        string="사양",
        domain=[("config_type", "=", "specification")],
    )
    attachment_link = fields.Char(
        string="첨부 파일",
        help="파일 경로 또는 URL 입력",
    )
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
            if vals.get("eo_number", _("New")) == _("New"):
                vals["eo_number"] = (
                    self.env["ir.sequence"].next_by_code("iatf.drawing.spec.change")
                    or _("New")
                )
        return super().create(vals_list)
