from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestPumui(TransactionCase):
    """품의 통제 배터리 승격본 — 상신 가드·결재선 템플릿 자동·승인 전 청구/전기 차단·연계 대사."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "품의거래처"})
        cls.user = new_test_user(
            cls.env, login="uat_pumui_approver",
            groups="pumui_approval.group_pumui_user",
            company_id=cls.env.company.id,
            company_ids=[(6, 0, cls.env.company.ids)],
        )
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

    def _approved_pumui(self):
        p = self._pumui()
        p.action_submit_approval()
        p.approval_request_id.sudo().with_user(self.user).action_approve()
        self.assertEqual(p.approval_state, "approved")
        return p

    def test_direct_line_change_requires_new_approval(self):
        p = self._approved_pumui()
        previous = p.approval_request_id
        p.line_ids.write({"price_unit": 60000})
        self.assertNotEqual(p.approval_state, "approved")
        self.assertNotEqual(p.approval_request_id, previous)
        self.assertEqual(previous.state, "approved")

    def test_direct_line_create_and_delete_invalidate_approval(self):
        p = self._approved_pumui()
        self.env["pumui.request.line"].create({
            "pumui_id": p.id, "name": "추가 항목", "quantity": 1, "price_unit": 100,
        })
        self.assertNotEqual(p.approval_state, "approved")
        other = self._approved_pumui()
        other.line_ids.unlink()
        self.assertNotEqual(other.approval_state, "approved")

    def test_move_line_invalidates_both_parents(self):
        source, target = self._approved_pumui(), self._approved_pumui()
        source.line_ids.write({"pumui_id": target.id})
        self.assertNotEqual(source.approval_state, "approved")
        self.assertNotEqual(target.approval_state, "approved")

    def test_direct_line_edit_during_review_starts_new_revision(self):
        p = self._pumui()
        p.action_submit_approval()
        previous = p.approval_request_id
        p.line_ids.write({"quantity": 3})
        self.assertNotEqual(p.approval_request_id, previous)
        self.assertEqual(p.approval_state, "draft")

    def test_posted_invoice_locks_invoiced_lines_and_structure(self):
        """전체 청구·전기 뒤: 청구 연결 자체는 승인 무효화 아님, 청구된 행·거래처·항목 구조 변경은 차단, 승인 근거 보존."""
        p = self._approved_pumui()
        p.action_create_invoice()
        self.assertEqual(p.approval_state, "approved", "청구 연결 자체는 승인 무효화 대상 아님")
        p.move_ids.action_post()
        previous = p.approval_request_id
        for attempt in (lambda: p.line_ids.write({"quantity": 3}), lambda: p.line_ids.unlink(),
                        lambda: p.write({"partner_id": self.env["res.partner"].create({"name": "다른 업체"}).id}),
                        lambda: p.write({"line_ids": [(0, 0, {"name": "추가", "quantity": 1, "price_unit": 1})]})):
            with self.assertRaises(UserError), self.env.cr.savepoint():
                attempt()
        self.assertEqual(p.approval_state, "approved")
        self.assertEqual(p.approval_request_id, previous)
        self.assertEqual(p.line_ids.quantity, 2)

    def test_line_create_via_context_default_invalidates_approval(self):
        p = self._approved_pumui()
        self.env["pumui.request.line"].with_context(default_pumui_id=p.id).create({
            "name": "컨텍스트 경로 항목", "quantity": 1, "price_unit": 10})
        self.assertNotEqual(p.approval_state, "approved")

    def test_create_with_lines_has_no_reset_recursion_and_still_approves(self):
        p = self._pumui()   # Command.create 라인 → 라인 create 가 부모 write 를 부르는 경로
        self.assertIn(p.approval_state, (False, "draft"))
        self.assertEqual(len(p.line_ids), 1)
        p.action_submit_approval()
        p.approval_request_id.sudo().with_user(self.user).action_approve()
        self.assertEqual(p.approval_state, "approved")

    def test_move_line_into_parent_with_posted_invoice_blocked(self):
        target = self._approved_pumui()
        target.action_create_invoice()
        target.move_ids.action_post()
        source = self._approved_pumui()
        with self.assertRaises(UserError), self.env.cr.savepoint():
            source.line_ids.write({"pumui_id": target.id})
        self.assertEqual(source.line_ids.pumui_id, source)
        self.assertEqual(target.approval_state, "approved")

    def test_direct_stored_amount_write_is_evidence_change(self):
        p = self._approved_pumui()
        previous = p.approval_request_id
        amount = p.amount_total
        # 2026-10-14: the agreed PR39 policy rejects computed-value tampering
        # before it can alter either the approved amount or its evidence.
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            p.line_ids.write({"price_total": 9999999})
        self.assertEqual(p.amount_total, amount)
        self.assertEqual(p.approval_request_id, previous)
        self.assertEqual(p.approval_state, "approved")

    def test_ordinary_pumui_uninvoiced_remainder_can_be_corrected_posted_line_locked(self):
        """계약금 행만 청구·전기한 뒤: 미청구 잔금 행 정정은 허용(결재 초기화), 전기된 행·항목 추가는 차단(050 R3)."""
        p = self._pumui(line_ids=[(0, 0, {"name": "계약금", "quantity": 4, "price_unit": 100, "payment_stage": "down"}),
                                  (0, 0, {"name": "잔금", "quantity": 6, "price_unit": 100, "payment_stage": "balance"})])
        p.action_submit_approval()
        p.approval_request_id.sudo().with_user(self.user).action_approve()
        p.action_create_invoice(stage="down")
        down = p.line_ids.filtered(lambda l: l.payment_stage == "down")
        remainder = p.line_ids.filtered(lambda l: l.payment_stage == "balance")
        self.assertTrue(down.invoice_line_id and not remainder.invoice_line_id, "계약금 행만 청구돼야 진짜 미청구 잔여 시험이다")
        p.move_ids.action_post()
        posted_qty = down.invoice_line_id.quantity
        previous = p.approval_request_id
        remainder.write({"price_unit": 90})            # 미청구 잔여 정정 → 허용 + 결재 초기화
        self.assertEqual(remainder.price_unit, 90)
        self.assertNotEqual(p.approval_state, "approved")
        self.assertNotEqual(p.approval_request_id, previous)
        with self.assertRaises(UserError), self.env.cr.savepoint():
            down.write({"quantity": 3})               # 전기된 행 변경 → 차단
        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.env["pumui.request.line"].create({"pumui_id": p.id, "name": "추가", "quantity": 1, "price_unit": 1})
        with self.assertRaises(UserError), self.env.cr.savepoint():
            p.write({"line_ids": [(0, 0, {"name": "추가2", "quantity": 1, "price_unit": 1})]})
        with self.assertRaises(UserError), self.env.cr.savepoint():
            down.unlink()
        self.assertEqual((down.quantity, down.invoice_line_id.quantity), (4, posted_qty))

    def test_invoice_link_from_action_does_not_invalidate_approval(self):
        p = self._approved_pumui()
        p.action_create_invoice()
        self.assertEqual(p.approval_state, "approved")
        self.assertTrue(p.line_ids.invoice_line_id)
        # PR39 strict policy rejects external unlink instead of accepting it
        # and merely invalidating the approval.
        linked = p.line_ids.invoice_line_id
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            p.line_ids.write({"invoice_line_id": False})
        self.assertEqual(p.line_ids.invoice_line_id, linked)
        self.assertEqual(p.approval_state, "approved")

    def test_rpc_context_cannot_forge_invoice_link_token(self):
        """RPC 가 넣을 수 있는 boolean context 로는 청구 연결 해제/교체 가드를 우회하지 못한다(총괄 040-1)."""
        p = self._approved_pumui()
        p.action_create_invoice()
        self.assertEqual(p.approval_state, "approved")
        forged = p.line_ids.with_context(pumui_invoice_link=True)
        linked = p.line_ids.invoice_line_id
        with self.assertRaises(AccessError), self.env.cr.savepoint():
            forged.write({"invoice_line_id": False})
        self.assertEqual(p.line_ids.invoice_line_id, linked)
        self.assertEqual(p.approval_state, "approved")

    def _term(self, name, days):
        return self.env["account.payment.term"].create({"name": name, "line_ids": [(0, 0, {
            "value": "percent", "value_amount": 100, "nb_days": days})]})

    def test_invoice_due_date_preserves_payment_terms(self):
        """지급조건 30일은 그 계산을 보존, 즉시결제는 발행일, 지급조건 없음은 비어 있을 때만 발행일로 채운다(총괄 040-3)."""
        term30, term0 = self._term("SYNTHETIC 30", 30), self._term("SYNTHETIC 0", 0)
        for term, expected_delta in ((term30, 30), (term0, 0), (None, 0)):
            partner = self.env["res.partner"].create({"name": "품의거래처 %s" % (term.name if term else "무조건"),
                                                     "property_supplier_payment_term_id": term.id if term else False})
            p = self._pumui(partner_id=partner.id)
            p.action_submit_approval()
            p.approval_request_id.sudo().with_user(self.user).action_approve()
            p.action_create_invoice()
            move = p.move_ids
            self.assertTrue(move.invoice_date_due, "만기일이 비어 있으면 코어 매입채무 제약에 걸린다")
            self.assertEqual((move.invoice_date_due - move.invoice_date).days, expected_delta,
                             "지급조건 계산이 덮어써졌다: %s" % (term and term.name))

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

    def test_manual_vendor_bills_can_share_matching_purchase_request(self):
        p = self._pumui()
        first = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner.id,
            "invoice_date": "2026-07-01",
            "pumui_id": p.id,
            "invoice_line_ids": [(0, 0, {
                "name": "월도품 1차",
                "quantity": 1,
                "price_unit": 40000,
            })],
        })
        second = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner.id,
            "invoice_date": "2026-08-01",
            "pumui_id": p.id,
            "invoice_line_ids": [(0, 0, {
                "name": "월도품 2차",
                "quantity": 1,
                "price_unit": 60000,
            })],
        })

        self.assertEqual(first.pumui_id, p)
        self.assertEqual(second.pumui_id, p)
        self.assertEqual(p.move_count, 2)
        self.assertAlmostEqual(p.invoiced_amount, 100000.0, delta=0.01)
        self.assertAlmostEqual(p.uninvoiced_amount, 0.0, delta=0.01)
        self.assertAlmostEqual(p.amount_diff, 0.0, delta=0.01)
        with self.assertRaises(UserError):
            p.action_create_invoice()
        with self.assertRaises(UserError):
            p.unlink()

    def test_manual_pumui_link_rejects_wrong_partner_or_document_type(self):
        p = self._pumui()
        other_partner = self.env["res.partner"].create({"name": "다른 거래처"})

        with self.assertRaises(ValidationError):
            self.env["account.move"].create({
                "move_type": "in_invoice",
                "partner_id": other_partner.id,
                "invoice_date": "2026-07-01",
                "pumui_id": p.id,
            })
        with self.assertRaises(ValidationError):
            self.env["account.move"].create({
                "move_type": "out_invoice",
                "partner_id": self.partner.id,
                "invoice_date": "2026-07-01",
                "pumui_id": p.id,
            })

    def test_vendor_bill_form_allows_draft_pumui_selection(self):
        arch = self.env.ref("pumui_approval.view_move_form_pumui").arch_db

        self.assertIn('name="pumui_id" string="품의서"', arch)
        self.assertIn('readonly="state != \'draft\'"', arch)
        self.assertIn("('pumui_type', '=', 'purchase')", arch)
        self.assertIn('string="품의 결재상태"', arch)

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
