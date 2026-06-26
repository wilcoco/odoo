from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfControlPlan(models.Model):
    _name = "iatf.control.plan"
    _description = "Control Plan (IATF 16949 §8.5.1.1)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="CP 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    cp_type = fields.Selection(
        [
            ("prototype", "시작품"),
            ("pre_launch", "양산 선행"),
            ("production", "양산"),
        ],
        string="관리계획서 유형", required=True, default="production", tracking=True,
    )

    product_id = fields.Many2one("product.product", string="제품")
    bom_id = fields.Many2one("mrp.bom", string="BOM",
                             help="이 제품의 BOM 구조 (G1 연동) — 다단계 구성품 참조")

    @api.onchange("product_id")
    def _onchange_product_id_bom(self):
        if self.product_id and not self.bom_id:
            self.bom_id = self.env["mrp.bom"]._bom_find(self.product_id).get(self.product_id)
    part_number = fields.Char(string="부품 번호")
    customer_id = fields.Many2one("res.partner", string="고객")
    revision = fields.Char(string="개정", default="01")
    revision_date = fields.Date(string="개정일", default=fields.Date.today)

    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    team_member_ids = fields.Many2many("res.users", string="핵심 팀원")

    fmea_id = fields.Many2one("iatf.fmea", string="관련 FMEA")
    apqp_project_id = fields.Many2one("iatf.apqp.project", string="APQP 프로젝트")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")

    line_ids = fields.One2many("iatf.control.plan.line", "control_plan_id", string="관리계획서 항목")
    line_count = fields.Integer(compute="_compute_line_count")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("review", "검토 중"),
            ("approved", "승인됨"),
            ("obsolete", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("line_ids")
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.control.plan") or _("New")
        return super().create(vals_list)

    def action_submit_review(self):
        self.write({"state": "review"})

    def action_approve(self):
        self.write({"state": "approved"})

    def action_obsolete(self):
        self.write({"state": "obsolete"})

    def action_reset_draft(self):
        self.write({"state": "draft"})
