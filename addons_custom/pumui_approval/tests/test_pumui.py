from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPumui(TransactionCase):
    """품의 통제 배터리 승격본 — 상신 가드·결재선 템플릿 자동·승인 전 청구/전기 차단·연계 대사."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "품의거래처"})
        cls.user = cls.env["res.users"].search([("share", "=", False)], limit=1)
        cls.env["iatf.approval.template"].create({
            "name": "T-기본", "line_ids": [(0, 0, {"sequence": 1, "user_id": cls.user.id})]})

    def _pumui(self, **vals):
        base = {"title": "T-품의", "partner_id": self.partner.id, "pumui_type": "purchase",
                "company_id": self.env.company.id,
                "line_ids": [(0, 0, {"name": "자재", "quantity": 2, "price_unit": 50000})]}
        base.update(vals)
        return self.env["pumui.request"].create(base)

    def test_submit_requires_lines(self):
        p = self._pumui(line_ids=False)
        with self.assertRaises(UserError):
            p.action_submit_approval()

    def test_template_autofill_and_manual_priority(self):
        p = self._pumui()
        p.action_submit_approval()
        self.assertEqual(len(p.approval_line_ids), 1, "템플릿 자동 구성")
        p2 = self._pumui(approval_line_ids=[(0, 0, {"sequence": 1, "user_id": self.user.id}),
                                            (0, 0, {"sequence": 2, "user_id": self.user.id})])
        p2.action_submit_approval()
        self.assertEqual(len(p2.approval_line_ids), 2, "수동 결재선 우선")

    def test_invoice_blocked_before_approval(self):
        p = self._pumui()
        with self.assertRaises(UserError):
            p.action_create_invoice()

    def test_post_blocked_for_unapproved_link(self):
        p = self._pumui()
        move = self.env["account.move"].create({
            "move_type": "in_invoice", "partner_id": self.partner.id,
            "invoice_date": "2026-07-01", "pumui_id": p.id,
            "invoice_line_ids": [(0, 0, {"name": "x", "quantity": 1, "price_unit": 100})]})
        with self.assertRaises(UserError):
            move.action_post()

    def test_full_chain_and_reconcile(self):
        p = self._pumui()
        p.action_submit_approval()
        p.approval_request_id.sudo().with_user(self.user).action_approve()
        self.assertEqual(p.approval_state, "approved")
        p.action_create_invoice()
        inv = p.move_ids
        self.assertEqual(len(inv), 1)
        self.assertEqual(inv.pumui_id, p)
        self.assertTrue(all(p.line_ids.mapped("invoiced")))
        with self.assertRaises(UserError):
            p.action_create_invoice()  # 미청구 항목 없음 — 이중 청구 차단
        inv.invoice_date = "2026-07-01"
        inv.action_post()
        self.assertEqual(inv.state, "posted")
        self.assertEqual(p.billing_status, "invoiced")
        self.assertAlmostEqual(p.amount_diff, 0.0, delta=0.01, msg="품의-청구 대사 0")
