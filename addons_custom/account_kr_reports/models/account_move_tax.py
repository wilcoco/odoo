from odoo import api, fields, models, _

INV_TYPES = ("out_invoice", "in_invoice", "out_refund", "in_refund")


class AccountMove(models.Model):
    """리포트 #15·#16·#17·#18: 한국식 과세유형·증빙종류·승인번호(중복차단)·수정분 연결."""
    _inherit = "account.move"

    kr_tax_type = fields.Selection(
        [("taxable", "과세"), ("zero", "영세"), ("exempt", "면세")],
        string="과세 구분", compute="_compute_kr_tax_type", store=True, readonly=False,
        index=True, tracking=True,
        help="라인 세금에서 자동 추정(과세: 세율>0 / 영세: 0% 세금 존재 / 면세: 세금 없음).\n"
             "직접 고르면 그 값이 유지되고, 라인 세금이 해당 구분에 맞게 바뀝니다.")
    kr_tax_type_manual = fields.Boolean(
        string="과세 구분 수동 지정", copy=False, default=False,
        help="사용자가 과세 구분을 직접 고른 전표. 라인 세금이 바뀌어도 자동 추정이 덮어쓰지 않는다.")
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
            # 사용자가 직접 고른 전표는 덮어쓰지 않는다 —
            # 면세로 바꿔도 라인 세금 변경 때마다 과세로 되돌아가던 문제
            if mv.kr_tax_type_manual:
                continue
            mv.kr_tax_type = mv._kr_auto_tax_type()

    def _kr_auto_tax_type(self):
        """라인 세금에서 추정한 과세 구분 (과세>0 / 영세 0% / 세금없음 면세)."""
        self.ensure_one()
        taxes = self.invoice_line_ids.filtered(
            lambda l: l.display_type == "product").mapped("tax_ids")
        if not taxes:
            return "exempt"
        if any(t.amount > 0 for t in taxes):
            return "taxable"
        return "zero"

    def _kr_tax_for_type(self, tax_type):
        """과세 구분에 맞는 세금 코드 — 한국 세목(l10n_kr) 명명 규칙 기준.

        과세: 10% TI / 영세: 0% ... ZR(영세율) / 면세: 0% ... TF(면세).
        면세도 **세금 코드가 있어야** 분개와 부가세 신고 태그가 맞는다
        (세금을 비워두면 신고 자료에서 빠진다).
        """
        self.ensure_one()
        use = "sale" if self.move_type in ("out_invoice", "out_refund") else "purchase"
        Tax = self.env["account.tax"]
        base = [("type_tax_use", "=", use), ("company_id", "=", self.company_id.id)]
        if tax_type == "taxable":
            return (Tax.search(base + [("name", "=", "10% TI")], limit=1)
                    or Tax.search(base + [("amount", "=", 10), ("amount_type", "=", "percent")], limit=1))
        if tax_type == "zero":
            return (Tax.search(base + [("name", "like", "ZR")], limit=1)
                    or Tax.search(base + [("amount", "=", 0)], limit=1))
        if tax_type == "exempt":
            return (Tax.search(base + [("name", "like", "TF")], limit=1)
                    or Tax.search(base + [("amount", "=", 0)], limit=1))
        return Tax.browse()

    @api.onchange("kr_tax_type")
    def _onchange_kr_tax_type(self):
        """과세 구분을 고르면 **라인 세금이 그에 맞게 바뀐다.**

        기존에는 구분만 바뀌고 세금은 그대로여서, 면세로 골라도 세액이 계산된
        분개가 만들어지고 담당자가 수동으로 맞춰야 했다.
        """
        for mv in self:
            if mv.move_type not in INV_TYPES or not mv.kr_tax_type:
                continue
            if mv.kr_tax_type == mv._kr_auto_tax_type():
                continue  # 라인 세금과 이미 일치 — 사용자의 의도적 변경이 아니다
            mv.kr_tax_type_manual = True
            tax = mv._kr_tax_for_type(mv.kr_tax_type)
            if not tax:
                return {"warning": {
                    "title": _("세금 코드 없음"),
                    "message": _("'%s' 에 해당하는 세금 코드를 찾지 못했습니다. "
                                 "회계 설정 › 세금을 확인해 주세요. 라인 세금은 그대로 둡니다.")
                                % dict(self._fields["kr_tax_type"].selection).get(mv.kr_tax_type)}}
            for line in mv.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
                line.tax_ids = [(6, 0, tax.ids)]
            mv.kr_doc_type = "invoice" if mv.kr_tax_type == "exempt" else "tax_invoice"

    @api.depends("move_type", "amount_total")
    def _compute_kr_correction(self):
        # amount_total_signed 는 매입청구서(in_invoice)에서 항상 음수(오두 부호 규약)라
        # 정상 매입분이 전부 수정분으로 오판됐다 → 부호 없는 amount_total 로 판정
        for mv in self:
            mv.kr_is_correction = (
                mv.move_type in ("out_refund", "in_refund")
                or (mv.move_type in ("out_invoice", "in_invoice") and mv.amount_total < 0))
