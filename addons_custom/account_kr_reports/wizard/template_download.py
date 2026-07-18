import base64
import io

from odoo import fields, models

# 리포트 #15·#23 역발상: 외부 양식을 맞추는 게 아니라 오두가 표준 템플릿을 내려준다.
# 헤더는 오두 native import가 자동 매핑하는 기술 필드 경로 — 채워서 그대로 가져오기(Import) 가능.
TEMPLATES = {
    "tax_sale": {
        "filename": "오두_업로드_세금계산서_매출.csv",
        "headers": ["partner_id", "invoice_date", "kr_doc_type", "kr_tax_type",
                    "kr_approval_number", "kr_origin_number",
                    "invoice_line_ids/name", "invoice_line_ids/quantity",
                    "invoice_line_ids/price_unit", "invoice_line_ids/tax_ids"],
        "sample": ["㈜거래처명", "2026-01-31", "tax_invoice", "taxable",
                   "20260131-12345678-12345678", "",
                   "품목 설명", "1", "1000000", "매출 10%"],
        "help": "가져오기 대상: 회계 > 고객 > 청구서 (account.move, 가져오기 시 move_type=out_invoice 컨텍스트)",
    },
    "tax_purchase": {
        "filename": "오두_업로드_세금계산서_매입.csv",
        "headers": ["partner_id", "invoice_date", "kr_doc_type", "kr_tax_type",
                    "kr_approval_number", "kr_origin_number",
                    "invoice_line_ids/name", "invoice_line_ids/quantity",
                    "invoice_line_ids/price_unit", "invoice_line_ids/tax_ids"],
        "sample": ["㈜공급사명", "2026-01-31", "tax_invoice", "taxable",
                   "20260131-87654321-87654321", "",
                   "품목 설명", "1", "500000", "매입 10%"],
        "help": "가져오기 대상: 회계 > 구매처 > 공급자청구서 (account.move, move_type=in_invoice)",
    },
    "tax_sale_match": {
        "filename": "오두_매출_승인번호_매칭.csv",
        "headers": ["approval_number", "vat", "date", "total"],
        "sample": ["20260131-12345678-12345678", "123-45-67890", "2026-01-31", "1100000"],
        "help": "회계 점검·조회(K) > 매출 승인번호 매칭 위저드 (기존 posted 매출 청구서에 백필)",
    },
    "bank": {
        "filename": "오두_업로드_은행거래내역.csv",
        "headers": ["date", "payment_ref", "partner_id", "amount"],
        "sample": ["2026-01-31", "입금 ㈜거래처명 (통장 적요 그대로)", "㈜거래처명", "1100000"],
        "help": "가져오기 대상: 해당 은행 저널 > 명세서 라인 (account.bank.statement.line). "
                "출금은 amount 를 음수로. partner_id 는 비워도 됨(적요로 사후 매칭).",
    },
}


class KrTemplateDownload(models.TransientModel):
    """업로드 표준 템플릿 다운로드 — 오두 기준 항목으로 엑셀/CSV 골격 제공."""
    _name = "kr.template.download"
    _description = "업로드 템플릿 다운로드"

    template_type = fields.Selection(
        [("tax_sale", "세금계산서 매출분"), ("tax_purchase", "세금계산서 매입분"),
         ("tax_sale_match", "매출 승인번호 매칭용"), ("bank", "은행 거래내역")],
        string="템플릿 종류", required=True, default="tax_sale")
    file = fields.Binary(string="템플릿 파일", readonly=True)
    filename = fields.Char(string="파일명")
    usage = fields.Text(string="사용 방법", readonly=True)

    def action_generate(self):
        self.ensure_one()
        spec = TEMPLATES[self.template_type]
        buf = io.StringIO()
        buf.write(",".join(spec["headers"]) + "\r\n")
        buf.write(",".join('"%s"' % v for v in spec["sample"]) + "\r\n")
        # 엑셀 한글 깨짐 방지: UTF-8 BOM
        data = ("\ufeff" + buf.getvalue()).encode("utf-8")
        self.write({
            "file": base64.b64encode(data),
            "filename": spec["filename"],
            "usage": ("1) 이 파일을 내려받아 2행(예시)을 지우고 데이터를 채웁니다.\n"
                      "2) %s 화면에서 '가져오기(Import)'로 업로드 — 헤더가 오두 필드와 "
                      "자동 매핑됩니다.\n"
                      "3) 승인번호(kr_approval_number)는 중복 업로드가 자동 차단됩니다.")
                     % spec["help"],
        })
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new", "name": "업로드 템플릿 다운로드"}
