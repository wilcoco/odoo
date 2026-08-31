from odoo import fields, models, _

INV_TYPES = ("out_invoice", "in_invoice", "out_refund", "in_refund")


class KrCloseChecklist(models.TransientModel):
    """마감 전 체크리스트 확장 — 부가세 신고 전 검증 (리포트 #18)."""
    _inherit = "kr.close.checklist"

    tax_no_approval = fields.Integer(string="승인번호 없는 세금계산서", compute="_compute_tax_checks")
    tax_no_vat_partner = fields.Integer(string="사업자번호 없는 거래처의 세금계산서", compute="_compute_tax_checks")
    correction_no_origin = fields.Integer(string="원본번호 없는 수정/마이너스분", compute="_compute_tax_checks")
    correction_origin_unmatched = fields.Integer(
        string="원본 전표를 찾지 못한 수정/마이너스분",
        compute="_compute_tax_checks",
        help="원본 승인번호는 있지만 같은 회사에서 해당 승인번호의 원본 전표를 찾지 못한 건")
    residual_mismatch = fields.Integer(
        string="청구서↔원장 잔액 불일치 거래처", compute="_compute_tax_checks",
        help="거래처별 매출채권/매입채무 원장 잔액과 미결 청구서 잔액 합이 다른 경우 — "
             "수기 전표·미조정 결제가 원인 (리포트 #27)")

    def _kr_residual_mismatch_partner_ids(self):
        """원장(AR/AP aml 잔액) vs 청구서(amount_residual_signed) 거래처별 대사."""
        AML = self.env["account.move.line"]
        AM = self.env["account.move"]
        mismatched = set()
        for acc_type, inv_types in (
                ("asset_receivable", ("out_invoice", "out_refund")),
                ("liability_payable", ("in_invoice", "in_refund"))):
            ledger = {}
            for g in AML.read_group(
                    [("account_id.account_type", "=", acc_type),
                     ("parent_state", "=", "posted"), ("partner_id", "!=", False)],
                    ["amount_residual:sum"], ["partner_id"]):
                ledger[g["partner_id"][0]] = g["amount_residual"] or 0.0
            invoiced = {}
            for g in AM.read_group(
                    [("move_type", "in", inv_types), ("state", "=", "posted"),
                     ("partner_id", "!=", False)],
                    ["amount_residual_signed:sum"], ["partner_id"]):
                invoiced[g["partner_id"][0]] = g["amount_residual_signed"] or 0.0
            for pid in set(ledger) | set(invoiced):
                if abs(ledger.get(pid, 0.0) - invoiced.get(pid, 0.0)) > 0.01:
                    mismatched.add(pid)
        return list(mismatched)

    def _kr_unmatched_origin_move_ids(self):
        """원본 승인번호가 실제 정본 전표와 연결되지 않는 수정분을 찾는다."""
        AM = self.env["account.move"]
        corrections = AM.search([
            ("move_type", "in", INV_TYPES),
            ("state", "!=", "cancel"),
            ("kr_is_correction", "=", True),
            ("kr_origin_number", "!=", False),
        ])
        unmatched = []
        for move in corrections:
            original = AM._kr_find_by_approval_number(
                move.kr_origin_number,
                company=move.company_id,
                move_types=INV_TYPES,
                limit=1,
            )
            if not original:
                unmatched.append(move.id)
        return unmatched

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
            rec.correction_origin_unmatched = len(
                rec._kr_unmatched_origin_move_ids()
            )
            rec.residual_mismatch = len(self._kr_residual_mismatch_partner_ids())

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

    def action_correction_origin_unmatched(self):
        return self._act(
            _("원본 전표를 찾지 못한 수정/마이너스분"),
            "account.move",
            [("id", "in", self._kr_unmatched_origin_move_ids())],
        )

    def action_residual_mismatch(self):
        pids = self._kr_residual_mismatch_partner_ids()
        return self._act(_("청구서↔원장 잔액 불일치 — 해당 거래처 미결 원장 라인"),
                         "account.move.line",
                         [("partner_id", "in", pids), ("parent_state", "=", "posted"),
                          ("account_id.account_type", "in",
                           ("asset_receivable", "liability_payable")),
                          ("amount_residual", "!=", 0)])
