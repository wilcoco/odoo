from odoo import api, fields, models, _


class SqFieldRecord(models.Model):
    """현장/절차 증빙 기록 — Odoo 트랜잭션 데이터가 없는 SQ 항목(3정5행·정성품질·안전 등)의
    디지털 증빙 홈. 각 기록이 sq.criteria 에 연결돼 해당 항목의 증빙으로 조회됨."""
    _name = "sq.field.record"
    _description = "SQ 현장/절차 증빙 기록"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "record_date desc, id desc"

    name = fields.Char(string="번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    criteria_id = fields.Many2one("sq.criteria", string="SQ 평가항목", required=True, index=True,
                                  ondelete="cascade", tracking=True)
    category_id = fields.Many2one(related="criteria_id.category_id", store=True, string="대분류")
    record_date = fields.Date(string="기록일", default=fields.Date.today, required=True, tracking=True)
    title = fields.Char(string="제목", required=True)
    result = fields.Selection(
        [("conform", "적합"), ("observe", "관찰/개선요"), ("nonconform", "부적합")],
        string="결과", default="conform", tracking=True,
    )
    description = fields.Text(string="내용 / 관찰사항")
    responsible_id = fields.Many2one("res.users", string="담당자", default=lambda self: self.env.user)
    attachment_ids = fields.Many2many("ir.attachment", string="증빙 첨부")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("sq.field.record") or _("New")
        return super().create(vals_list)
