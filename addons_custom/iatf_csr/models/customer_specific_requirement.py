from odoo import api, fields, models, _


class IatfCustomerSpecificRequirement(models.Model):
    _name = "iatf.csr"
    _description = "고객 특수요구사항 (CSR)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "customer_id, sequence"

    name = fields.Char(
        string="CSR 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    customer_id = fields.Many2one("res.partner", string="고객", required=True, tracking=True)
    title = fields.Char(string="요구사항 제목", required=True, tracking=True)
    sequence = fields.Integer(default=10)

    category = fields.Selection(
        [
            ("ppap", "PPAP 요구사항"),
            ("packaging", "포장 / 라벨링"),
            ("shipping", "출하 / 납품"),
            ("quality", "품질 기준"),
            ("inspection", "검사 요구사항"),
            ("documentation", "문서 요구사항"),
            ("traceability", "추적성"),
            ("warranty", "보증"),
            ("notification", "변경 통보"),
            ("special_process", "특수공정"),
            ("material", "자재 / 환경물질"),
            ("audit", "심사 요구사항"),
            ("other", "기타"),
        ],
        string="카테고리", required=True, default="quality", tracking=True,
    )

    # ── 요구사항 상세 ──
    description = fields.Html(string="요구사항 상세", required=True)
    reference_document = fields.Char(string="참조 문서 / 규격",
                                      help="예: GM-1927, Ford GSRS, VW Formel-Q")
    revision = fields.Char(string="개정")
    effective_date = fields.Date(string="적용일")
    expiry_date = fields.Date(string="만료일")

    # ── 해당 제품 ──
    product_ids = fields.Many2many("product.product", string="해당 제품")
    applies_to_all = fields.Boolean(string="전 제품 적용", default=False)

    # ── 내부 대응 ──
    compliance_status = fields.Selection(
        [
            ("compliant", "적합"),
            ("partial", "부분 적합"),
            ("non_compliant", "부적합"),
            ("under_review", "검토 중"),
            ("not_applicable", "해당없음"),
        ],
        string="적합 현황", default="under_review", tracking=True,
    )
    internal_action = fields.Html(string="내부 대응 조치")
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    review_date = fields.Date(string="검토일")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("active", "활성"),
            ("review", "검토 필요"),
            ("obsolete", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.csr") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_review(self):
        self.write({"state": "review"})

    def action_obsolete(self):
        self.write({"state": "obsolete"})
