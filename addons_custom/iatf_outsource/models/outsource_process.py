from odoo import api, fields, models, _


class IatfOutsourceProcess(models.Model):
    _name = "iatf.outsource.process"
    _description = "외주공정 등록 (IATF 16949 §8.4)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(string="외주공정명", required=True, tracking=True)
    code = fields.Char(string="공정 코드")

    process_type = fields.Selection(
        [
            ("heat_treatment", "열처리"),
            ("plating", "도금"),
            ("painting", "도장"),
            ("machining", "가공"),
            ("welding", "용접"),
            ("assembly", "조립"),
            ("test", "시험/검사"),
            ("other", "기타"),
        ],
        string="공정 유형", required=True, default="heat_treatment", tracking=True,
    )
    is_special_process = fields.Boolean(string="특수공정 여부", default=False,
                                         help="CQI 해당 여부")
    cqi_standard = fields.Char(string="CQI 표준", help="예: CQI-9, CQI-11, CQI-12")

    # ── 외주업체 ──
    supplier_id = fields.Many2one("res.partner", string="외주업체", required=True,
                                   domain="[('supplier_rank','>',0)]", tracking=True)
    backup_supplier_id = fields.Many2one("res.partner", string="대체 업체",
                                          domain="[('supplier_rank','>',0)]")

    # ── 품질 기준 ──
    quality_requirements = fields.Html(string="품질 요구사항")
    inspection_method = fields.Selection(
        [
            ("incoming", "수입검사"),
            ("certificate", "성적서 확인"),
            ("audit", "공정 심사"),
            ("skip", "면제"),
        ],
        string="검증 방법", default="incoming",
    )
    specification_ids = fields.Many2many("iatf.document", string="적용 규격/사양서")

    # ── 해당 제품 ──
    product_ids = fields.Many2many("product.product", string="해당 제품")

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)

    # ── 실적 ──
    order_ids = fields.One2many("iatf.outsource.order", "process_id", string="외주 발주 이력")

    document_ids = fields.Many2many(
        "iatf.document", "iatf_outsource_process_doc_rel", "process_id", "doc_id",
        string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [("draft", "등록"), ("active", "활성"), ("inactive", "비활성")],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    def action_activate(self):
        self.write({"state": "active"})

    def action_deactivate(self):
        self.write({"state": "inactive"})
