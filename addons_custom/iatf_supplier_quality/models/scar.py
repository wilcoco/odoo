from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfScar(models.Model):
    _name = "iatf.scar"
    _description = "Supplier Corrective Action Request (SCAR)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="SCAR 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    supplier_id = fields.Many2one("res.partner", string="협력업체", required=True,
                                   domain="[('supplier_rank','>',0)]", tracking=True)
    issue_date = fields.Date(string="발행일", default=fields.Date.today, required=True)
    response_due_date = fields.Date(string="답변 기한", required=True, tracking=True)

    # ── Problem ──
    product_id = fields.Many2one("product.product", string="영향 제품")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")
    quantity_affected = fields.Float(string="영향 수량")
    problem_description = fields.Html(string="문제 설명", required=True)
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="관련 부적합")

    # ── Supplier response ──
    containment_action = fields.Html(string="격리 조치 (협력업체)")
    root_cause = fields.Html(string="근본원인 (협력업체)")
    corrective_action = fields.Html(string="시정조치 (협력업체)")
    preventive_action = fields.Html(string="예방조치 (협력업체)")
    response_date = fields.Date(string="답변 접수일")

    # ── Verification ──
    verification_result = fields.Html(string="검증 결과")
    verified_by = fields.Many2one("res.users", string="검증자")
    effective = fields.Selection(
        [("yes", "유효"), ("no", "무효"), ("partial", "부분 유효")],
        string="유효성",
    )

    responsible_id = fields.Many2one("res.users", string="내부 담당자",
                                      default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("issued", "협력업체 발행"),
            ("response", "답변 접수"),
            ("verification", "검증"),
            ("closed", "종료"),
        ],
        default="draft", tracking=True,
    )
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.scar") or _("New")
        return super().create(vals_list)

    def action_issue(self):
        self.write({"state": "issued"})

    def action_receive_response(self):
        self.write({"state": "response", "response_date": fields.Date.today()})

    def action_verify(self):
        self.write({"state": "verification"})

    def action_close(self):
        for rec in self:
            if not rec.effective:
                raise UserError(_("Please set the effectiveness evaluation before closing."))
        self.write({"state": "closed"})
