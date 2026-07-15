from odoo import fields, models, _

INV_TYPES = ("out_invoice", "in_invoice", "out_refund", "in_refund")


class KrCloseChecklist(models.TransientModel):
    """마감 전 체크리스트 확장 — 부가세 신고 전 검증 (리포트 #18)."""
    _inherit = "kr.close.checklist"

    tax_no_approval = fields.Integer(string="승인번호 없는 세금계산서", compute="_compute_tax_checks")
    tax_no_vat_partner = fields.Integer(string="사업자번호 없는 거래처의 세금계산서", compute="_compute_tax_checks")
    correction_no_origin = fields.Integer(string="원본번호 없는 수정/마이너스분", compute="_compute_tax_checks")

    def _compute_tax_checks(self):
        AM = self.env["account.move"]
        for rec in self:
            rec.tax_no_approval = AM.search_count([
                ("move_type", "in", INV_TYPES), ("state", "=", "posted"),
                ("kr_doc_type", "=", "tax_invoice"), ("kr_approval_number", "=", False)])
            rec.tax_no_vat_partner = AM.search_count([
                ("move_type", "in", INV_TYPES), ("state", "=", "posted"),
                ("kr_doc_type", "=", "tax_invoice"), ("partner_id.vat", "=", False)])
            rec.correction_no_origin = AM.search_count([
                ("move_type", "in", INV_TYPES), ("state", "!=", "cancel"),
                ("kr_is_correction", "=", True), ("kr_origin_number", "=", False)])

    def action_tax_no_approval(self):
        return self._act(_("승인번호 없는 세금계산서"), "account.move",
                         [("move_type", "in", INV_TYPES), ("state", "=", "posted"),
                          ("kr_doc_type", "=", "tax_invoice"), ("kr_approval_number", "=", False)])

    def action_tax_no_vat_partner(self):
        return self._act(_("사업자번호 없는 거래처의 세금계산서"), "account.move",
                         [("move_type", "in", INV_TYPES), ("state", "=", "posted"),
                          ("kr_doc_type", "=", "tax_invoice"), ("partner_id.vat", "=", False)])

    def action_correction_no_origin(self):
        return self._act(_("원본번호 없는 수정/마이너스분"), "account.move",
                         [("move_type", "in", INV_TYPES), ("state", "!=", "cancel"),
                          ("kr_is_correction", "=", True), ("kr_origin_number", "=", False)])
