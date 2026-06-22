from odoo import api, fields, models, _


class IatfJig(models.Model):
    _name = "iatf.jig"
    _description = "지그(Jig) 대장"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "code"

    code = fields.Char(string="지그 번호", required=True, copy=False, tracking=True)
    name = fields.Char(string="지그명", required=True, tracking=True)
    jig_type = fields.Selection(
        [("paint", "도장지그"), ("assembly", "조립지그"), ("inspection", "검사지그"), ("other", "기타")],
        string="유형", tracking=True,
    )
    process_name = fields.Char(string="공정", help="회사양식 process")
    product_id = fields.Many2one("product.product", string="대상 제품 / 부품", tracking=True)
    state = fields.Selection(
        [("active", "사용"), ("inactive", "비사용"), ("disposed", "폐기")],
        string="상태", default="active", tracking=True,
    )
    record_ids = fields.One2many("iatf.jig.record", "jig_id", string="점검 기록")
    record_count = fields.Integer(compute="_compute_record_count")
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    def _compute_record_count(self):
        for rec in self:
            rec.record_count = len(rec.record_ids)

    def action_activate(self):
        self.write({"state": "active"})

    def action_inactive(self):
        self.write({"state": "inactive"})

    def action_dispose(self):
        self.write({"state": "disposed"})


class IatfJigRecord(models.Model):
    _name = "iatf.jig.record"
    _description = "지그 점검 기록"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "record_date desc, id desc"

    name = fields.Char(string="기록 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    jig_id = fields.Many2one("iatf.jig", string="지그", required=True, ondelete="cascade", tracking=True)
    record_type = fields.Selection(
        [("daily", "일상점검"), ("verification", "정도검증"), ("stripping", "박리(도장)")],
        string="기록 유형", required=True, tracking=True,
    )
    record_date = fields.Date(string="기록일", default=fields.Date.today, required=True)
    status = fields.Selection(
        [("normal", "정상"), ("abnormal", "이상"), ("repair", "수리필요")],
        string="상태", tracking=True,
    )
    measured_values = fields.Text(string="측정값")
    remarks = fields.Text(string="비고")
    performer_id = fields.Many2one("res.users", string="수행자", default=lambda self: self.env.user)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.jig.record") or _("New")
        return super().create(vals_list)
