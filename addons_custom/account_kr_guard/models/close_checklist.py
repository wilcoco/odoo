from odoo import api, fields, models, _

INV_TYPES = ("out_invoice", "in_invoice", "out_refund", "in_refund")


class KrCloseChecklist(models.TransientModel):
    """리포트 #28: 마감 전 체크리스트 — 문제 항목을 집계하고 드릴다운."""
    _name = "kr.close.checklist"
    _description = "마감 전 체크리스트"

    zero_total = fields.Integer(string="총계 0원 청구서", compute="_compute_all")
    draft_payments = fields.Integer(string="미전기(진행중) 결제", compute="_compute_all")
    unmatched_payments = fields.Integer(string="은행 미조정 결제", compute="_compute_all")
    partner_no_vat = fields.Integer(string="사업자번호 없는 거래처", compute="_compute_all")
    partner_dup_vat = fields.Integer(string="사업자번호 중복 거래처", compute="_compute_all")
    line_no_tax = fields.Integer(string="세금 없는 청구 라인", compute="_compute_all")
    unapproved_pumui_moves = fields.Integer(string="미승인 품의 연계 전표", compute="_compute_all")
    no_pumui_moves = fields.Integer(string="품의 미연계 청구서", compute="_compute_all")
    negative_invoices = fields.Integer(string="음수 금액 일반 청구서", compute="_compute_all")

    def _compute_all(self):
        AM = self.env["account.move"]
        AML = self.env["account.move.line"]
        AP = self.env["account.payment"]
        RP = self.env["res.partner"]
        for rec in self:
            rec.zero_total = AM.search_count([
                ("move_type", "in", INV_TYPES), ("state", "!=", "cancel"),
                ("amount_total", "=", 0)])
            rec.draft_payments = AP.search_count([("state", "=", "draft")])
            rec.unmatched_payments = AP.search_count([
                ("state", "in", ("posted", "in_process")), ("is_matched", "=", False)]) \
                if "is_matched" in AP._fields else 0
            rec.partner_no_vat = RP.search_count([
                ("vat", "=", False), "|", ("customer_rank", ">", 0), ("supplier_rank", ">", 0)])
            self.env.cr.execute(
                "SELECT count(*) FROM (SELECT vat FROM res_partner "
                "WHERE vat IS NOT NULL AND active GROUP BY vat HAVING count(*)>1) t")
            rec.partner_dup_vat = self.env.cr.fetchone()[0]
            rec.line_no_tax = AML.search_count([
                ("move_id.move_type", "in", INV_TYPES), ("move_id.state", "=", "posted"),
                ("display_type", "=", "product"), ("tax_ids", "=", False)])
            rec.unapproved_pumui_moves = AM.search_count([
                ("pumui_id", "!=", False), ("pumui_approval_state", "!=", "approved")])
            rec.no_pumui_moves = AM.search_count([
                ("move_type", "in", ("out_invoice", "in_invoice")),
                ("state", "!=", "cancel"), ("pumui_id", "=", False)])
            # amount_total_signed 는 매입청구서에서 항상 음수 → 전건 오탐이던 결함
            rec.negative_invoices = AM.search_count([
                ("move_type", "in", ("out_invoice", "in_invoice")),
                ("state", "!=", "cancel"), ("amount_total", "<", 0)])

    # ── 드릴다운 ──
    def _act(self, name, model, domain):
        return {"type": "ir.actions.act_window", "name": name, "res_model": model,
                "view_mode": "list,form", "domain": domain}

    def action_zero_total(self):
        return self._act(_("총계 0원 청구서"), "account.move",
                         [("move_type", "in", INV_TYPES), ("state", "!=", "cancel"), ("amount_total", "=", 0)])

    def action_draft_payments(self):
        return self._act(_("미전기 결제"), "account.payment", [("state", "=", "draft")])

    def action_unmatched_payments(self):
        return self._act(_("은행 미조정 결제"), "account.payment",
                         [("state", "in", ("posted", "in_process")), ("is_matched", "=", False)])

    def action_partner_no_vat(self):
        return self._act(_("사업자번호 없는 거래처"), "res.partner",
                         [("vat", "=", False), "|", ("customer_rank", ">", 0), ("supplier_rank", ">", 0)])

    def action_partner_dup_vat(self):
        self.env.cr.execute(
            "SELECT vat FROM res_partner WHERE vat IS NOT NULL AND active GROUP BY vat HAVING count(*)>1")
        vats = [r[0] for r in self.env.cr.fetchall()]
        return self._act(_("사업자번호 중복 거래처"), "res.partner", [("vat", "in", vats)])

    def action_line_no_tax(self):
        return self._act(_("세금 없는 청구 라인"), "account.move.line",
                         [("move_id.move_type", "in", INV_TYPES), ("move_id.state", "=", "posted"),
                          ("display_type", "=", "product"), ("tax_ids", "=", False)])

    def action_unapproved_pumui(self):
        return self._act(_("미승인 품의 연계 전표"), "account.move",
                         [("pumui_id", "!=", False), ("pumui_approval_state", "!=", "approved")])

    def action_no_pumui(self):
        return self._act(_("품의 미연계 청구서"), "account.move",
                         [("move_type", "in", ("out_invoice", "in_invoice")),
                          ("state", "!=", "cancel"), ("pumui_id", "=", False)])

    def action_negative(self):
        return self._act(_("음수 금액 일반 청구서"), "account.move",
                         [("move_type", "in", ("out_invoice", "in_invoice")),
                          ("state", "!=", "cancel"), ("amount_total", "<", 0)])

    @api.model
    def action_open(self):
        rec = self.create({})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": rec.id,
                "view_mode": "form", "target": "current", "name": _("마감 전 체크리스트")}
