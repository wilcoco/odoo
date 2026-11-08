"""478 묶음 A — 판정·근거 가드 회귀 시험 (공정·출하검사).

8070 실동작 점검에서 확인된 원 재현을 거부로 바꾸고, 정상 입력은 그대로
통과하는지 한 쌍씩 확인한다. 과거 레코드를 소급해 바꾸지 않는다.
"""
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestJudgementGuards(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.product = cls.env["product.product"].create({
            "name": "478A 시험 품목", "is_storable": True,
        })
        cls.PQC = cls.env["iatf.process.inspection"]

    def _pqc(self, **values):
        data = dict(product_id=self.product.id, company_id=self.company.id,
                    inspection_type="full", quantity_produced=10,
                    quantity_inspected=10, quantity_accepted=10, quantity_rejected=0,
                    inspector_id=self.env.uid, result="pass",
                    line_ids=[Command.create({
                        "characteristic_name": "외관", "characteristic_type": "visual",
                        "specification": "흠 없음", "measured_value": "양호", "result": "pass",
                    })])
        data.update(values)
        return self.PQC.create(data)

    # ── 수량 관계 (#31) ──────────────────────────────────────────
    def test_quantity_relations_rejected_and_normal_allowed(self):
        with self.assertRaises(ValidationError):
            self._pqc(quantity_produced=1, quantity_inspected=1,
                      quantity_accepted=2, quantity_rejected=0)
        with self.assertRaises(ValidationError):
            self._pqc(quantity_produced=10, quantity_inspected=11)
        with self.assertRaises(ValidationError):
            self._pqc(quantity_produced=-1)
        ok = self._pqc(quantity_produced=10, quantity_inspected=5,
                       quantity_accepted=5, quantity_rejected=0,
                       inspection_type="full")
        self.assertTrue(ok.id, "정상 수량은 저장되어야 한다")

    def test_sampling_keeps_disposition_outside_sample(self):
        # 샘플링은 '처분 합 <= 검사(샘플)' 를 강제하지 않는다. 생산 범위만 본다.
        rec = self._pqc(inspection_type="sampling", quantity_produced=100,
                        quantity_inspected=5, quantity_accepted=98, quantity_rejected=2)
        self.assertTrue(rec.id)

    # ── 판정 가드 (#31·#550·#556·#49) ───────────────────────────
    def _decide(self, rec):
        rec.action_start_inspection()
        return rec.action_decide()

    def test_blank_evidence_and_na_reason(self):
        rec = self._pqc(line_ids=[Command.create({
            "characteristic_name": "외관", "specification": "흠 없음",
            "measured_value": "   ", "result": "pass"})])
        with self.assertRaises(UserError):
            self._decide(rec)
        rec.line_ids.measured_value = "양호"
        self.assertTrue(self._decide(rec))

        na = self._pqc(line_ids=[Command.create({
            "characteristic_name": "치수", "specification": "10±0.1",
            "measured_value": "", "result": "na"})])
        with self.assertRaises(UserError):
            self._decide(na)
        na.line_ids.notes = "해당 공정 없음"
        with self.assertRaises(UserError):
            self._decide(na)  # 측정한 항목이 없으면 합격 불가

    def test_summary_fail_blocks_overall_pass(self):
        rec = self._pqc()
        if "dimension_result" in rec._fields:
            rec.dimension_result = "fail"
            with self.assertRaises(UserError):
                self._decide(rec)
            rec.dimension_result = "pass"
            self.assertTrue(self._decide(rec))

    def test_rejected_quantity_blocks_pass(self):
        rec = self._pqc(quantity_accepted=9, quantity_rejected=1, result="pass")
        with self.assertRaises(UserError):
            self._decide(rec)

    def test_full_quantity_balance_required(self):
        rec = self._pqc(quantity_produced=10, quantity_inspected=10,
                        quantity_accepted=8, quantity_rejected=0)
        with self.assertRaises(UserError):
            self._decide(rec)

    def test_sampling_plan_required_on_decide(self):
        rec = self._pqc(inspection_type="sampling", quantity_produced=100,
                        quantity_inspected=5, quantity_accepted=100, quantity_rejected=0)
        with self.assertRaises(UserError):
            self._decide(rec)
        rec.write({"sampling_plan": "AQL II 보통", "sample_size": 5,
                   "accept_number": 0})
        self.assertTrue(self._decide(rec))

    def test_draft_control_plan_rejected(self):
        plan = self.env["iatf.control.plan"].create({
            "title": "478A 초안 관리계획", "product_id": self.product.id})
        rec = self._pqc(control_plan_id=plan.id)
        if plan.state != "approved":
            with self.assertRaises(UserError):
                self._decide(rec)

    # ── 상태 전이 (#548) ────────────────────────────────────────
    def test_close_requires_decided(self):
        rec = self._pqc()
        rec.action_start_inspection()
        with self.assertRaises(UserError):
            rec.action_close()
        rec.action_decide()
        rec.action_close()
        self.assertEqual(rec.state, "closed")
        with self.assertRaises(UserError):
            rec.action_cancel(reason="시험")

    # ── AQL 입력 보존 (#553) ────────────────────────────────────
    def test_aql_uses_production_qty_and_keeps_input(self):
        rec = self._pqc(inspection_type="sampling", quantity_produced=0,
                        quantity_inspected=100, quantity_accepted=0, quantity_rejected=0)
        with self.assertRaises(UserError):
            rec.action_compute_aql_sample()
        rec.quantity_produced = 100
        rec.action_compute_aql_sample()
        first = (rec.sample_size, rec.quantity_inspected)
        rec.action_compute_aql_sample()
        self.assertEqual((rec.sample_size, rec.quantity_inspected), first,
                         "다시 계산해도 표본·검사 수량이 줄지 않아야 한다")
        self.assertEqual(rec.quantity_inspected, 100,
                         "사람이 입력한 검사 수량을 덮지 않는다")

    # ── 설정이 없을 때 권고 기본값이 쓰이는지 (1차 CI 실패 원인) ──
    def test_policy_defaults_apply_when_unset(self):
        """`ir.config_parameter.get_param` 은 키가 없으면 False 를 준다.

        그것을 "꺼짐" 으로 읽으면 설정을 건드리지 않은 DB 에서 모든 가드가
        조용히 비활성화된다. 없음은 권고 기본값으로 떨어져야 한다.
        """
        from odoo.addons.iatf_document_control.models.quality_guards import (
            policy_enabled, policy_value,
        )
        key = "quality.test_unset_key_478a"
        self.env["ir.config_parameter"].sudo().search([("key", "=", key)]).unlink()
        self.assertTrue(policy_enabled(self.env, key, True), "없음 → 권고 True")
        self.assertFalse(policy_enabled(self.env, key, False), "없음 → 권고 False")
        self.assertEqual(policy_value(self.env, key, "권고값"), "권고값")
        self.env["ir.config_parameter"].sudo().set_param(key, "0")
        self.assertFalse(policy_enabled(self.env, key, True), "0 은 꺼짐")
        self.env["ir.config_parameter"].sudo().set_param(key, "1")
        self.assertTrue(policy_enabled(self.env, key, False), "1 은 켜짐")

    # ── 아스트라 A-31-S01 / S02 회귀 ─────────────────────────────
    def test_manual_sample_size_is_not_overwritten(self):
        """사람이 적은 표본 수량을 사유 없이 덮지 않는다 (553 §3)."""
        rec = self._pqc(inspection_type="sampling", quantity_produced=100,
                        quantity_inspected=50, quantity_accepted=100,
                        quantity_rejected=0, sample_size=17,
                        sampling_plan="회사 표본계획")
        with self.assertRaises(UserError):
            rec.action_compute_aql_sample()
        self.assertEqual(rec.sample_size, 17, "덮이지 않아야 한다")
        rec.action_compute_aql_sample(overwrite_reason="간이표로 재산정 합의")
        self.assertEqual(rec.sample_size, 32)
        self.assertEqual(rec.quantity_inspected, 50, "검사 수량은 그대로")
        self.assertEqual(rec.sampling_plan, "회사 표본계획", "계획명도 그대로")

    def test_summary_is_computed_from_lines(self):
        """항목이 불합격이면 수동 요약이 합격이어도 요약이 불합격으로 계산된다."""
        rec = self._pqc(
            result="conditional", quantity_accepted=9, quantity_rejected=1,
            line_ids=[Command.create({
                "characteristic_name": "치수1", "characteristic_type": "dimensional",
                "specification": "10±0.1", "measured_value": "10.5", "result": "fail",
            })])
        rec.dimension_result = "pass"
        rec.action_start_inspection()
        rec.action_decide()
        self.assertEqual(rec.dimension_result, "fail",
                         "항목에서 계산된 요약이 수동 입력을 바로잡는다")

    def test_summary_blank_when_nothing_measured(self):
        rec = self._pqc(line_ids=[Command.create({
            "characteristic_name": "외관", "characteristic_type": "visual",
            "specification": "흠 없음", "measured_value": "양호", "result": "pass",
        })])
        rec.action_start_inspection()
        rec.action_decide()
        self.assertEqual(rec.visual_result, "pass")
