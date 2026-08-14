import base64
import csv
import io

from odoo import fields, models, _
from odoo.exceptions import UserError

# 리포트 후속(1번세션 제안 5): 매출 세금계산서 흐름.
# 매출 청구서는 오두가 발행 주체 → 홈택스 발행분을 새로 만들지 않고
# 기존 posted 청구서에 승인번호를 '백필 매칭'한다 (매입=생성, 매출=매칭).
MATCH_HEADERS = ["approval_number", "vat", "date", "total"]


class KrSalesTaxMatch(models.TransientModel):
    _name = "kr.sales.tax.match"
    _description = "매출 세금계산서 승인번호 매칭"

    file = fields.Binary(string="홈택스 발행분 CSV", required=True)
    filename = fields.Char()
    result = fields.Text(string="매칭 결과", readonly=True)

    def _parse_rows(self):
        try:
            raw = base64.b64decode(self.file).decode("utf-8-sig")
        except UnicodeDecodeError:
            raise UserError(_("UTF-8 CSV 파일만 지원합니다. 템플릿을 내려받아 사용하세요."))
        reader = csv.DictReader(io.StringIO(raw))
        missing = [h for h in MATCH_HEADERS if h not in (reader.fieldnames or [])]
        if missing:
            raise UserError(_("필수 컬럼 누락: %s — '업로드 템플릿 다운로드'의 매출 매칭 템플릿을 사용하세요.")
                            % ", ".join(missing))
        return [r for r in reader if any((v or "").strip() for v in r.values())]

    def action_match(self):
        self.ensure_one()
        AM = self.env["account.move"]
        matched, dup, ambiguous, unmatched = [], [], [], []
        for row in self._parse_rows():
            appr = (row["approval_number"] or "").strip()
            vat = (row["vat"] or "").strip().replace("-", "")
            total = float(row["total"] or 0)
            if not appr:
                continue
            if AM.search_count([("kr_approval_number", "=", appr)]):
                dup.append(appr)
                continue
            domain = [
                ("move_type", "in", ("out_invoice", "out_refund")),
                ("state", "=", "posted"),
                ("invoice_date", "=", row["date"]),
                ("kr_approval_number", "=", False),
            ]
            cands = AM.search(domain).filtered(
                lambda m: (m.partner_id.vat or "").replace("-", "") == vat
                and abs(abs(m.amount_total_signed) - abs(total)) < 1.0)
            if len(cands) == 1:
                cands.write({"kr_approval_number": appr, "kr_doc_type": "tax_invoice"})
                matched.append("%s → %s" % (appr, cands.name))
            elif not cands:
                unmatched.append("%s (%s %s %s)" % (appr, vat, row["date"], total))
            else:
                ambiguous.append("%s → 후보 %d건: %s" % (appr, len(cands), ", ".join(cands.mapped("name"))))
        self.result = (
            "매칭 %d건\n%s\n\n이미 등록된 승인번호(건너뜀) %d건\n%s\n\n"
            "후보 없음 %d건 — 청구서 미발행/금액·일자 불일치 확인 필요\n%s\n\n"
            "복수 후보(수동 확정 필요) %d건\n%s") % (
            len(matched), "\n".join(matched[:30]),
            len(dup), "\n".join(dup[:10]),
            len(unmatched), "\n".join(unmatched[:30]),
            len(ambiguous), "\n".join(ambiguous[:10]))
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new", "name": _("매출 세금계산서 매칭")}
