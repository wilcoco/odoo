from odoo import api, fields, models, _

INV_TYPES = ("out_invoice", "in_invoice", "out_refund", "in_refund")


class AccountMove(models.Model):
    """리포트 #15·#16·#17·#18: 한국식 과세유형·증빙종류·승인번호(중복차단)·수정분 연결."""
    _inherit = "account.move"

    kr_tax_type = fields.Selection(
        [("taxable", "과세"), ("zero", "영세"), ("exempt", "면세")],
        string="과세 구분", compute="_compute_kr_tax_type", store=True, readonly=False,
        index=True, tracking=True,
        help="라인 세금에서 자동 추정(과세: 세율>0 / 영세: 0% 세금 존재 / 면세: 세금 없음). 수정 가능")
    kr_doc_type = fields.Selection(
        [("tax_invoice", "세금계산서"), ("invoice", "계산서(면세)"), ("card", "카드"),
         ("cash_receipt", "현금영수증"), ("etc", "기타")],
        string="증빙 종류", default="tax_invoice", index=True, tracking=True)
    kr_approval_number = fields.Char(
        string="세금계산서 승인번호", copy=False, index=True, tracking=True,
        help="국세청 승인번호 — 중복 업로드 차단 기준 (리포트 #16)")
    kr_is_correction = fields.Boolean(
        string="수정/마이너스분", compute="_compute_kr_correction", store=True,
        help="환불 전표이거나 총액이 음수면 수정·마이너스 세금계산서로 표시")
    kr_origin_number = fields.Char(
        string="원본 세금계산서 번호", copy=False,
        help="수정/마이너스 세금계산서의 원본 승인번호 (리포트 #17)")
    kr_partner_vat = fields.Char(related="partner_id.vat", string="사업자등록번호")

    _sql_constraints = [
        ("kr_approval_number_uniq", "unique(kr_approval_number)",
         "이미 업로드된 세금계산서입니다. 승인번호와 거래처를 확인해주세요."),
    ]

    @api.depends("invoice_line_ids.tax_ids", "invoice_line_ids.tax_ids.amount")
    def _compute_kr_tax_type(self):
        for mv in self:
            if mv.move_type not in INV_TYPES:
                mv.kr_tax_type = False
                continue
            taxes = mv.invoice_line_ids.filtered(
                lambda l: l.display_type == "product").mapped("tax_ids")
            if not taxes:
                mv.kr_tax_type = "exempt"
            elif any(t.amount > 0 for t in taxes):
                mv.kr_tax_type = "taxable"
            else:
                mv.kr_tax_type = "zero"

    @api.depends("move_type", "amount_total_signed")
    def _compute_kr_correction(self):
        for mv in self:
            mv.kr_is_correction = (
                mv.move_type in ("out_refund", "in_refund")
                or (mv.move_type in ("out_invoice", "in_invoice") and mv.amount_total_signed < 0))
