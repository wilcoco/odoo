"""557 §2 — 전표 없는 포장·라벨 검사도 판정 근거를 남긴다.

아스트라 A-53-S01: 완결성 검사는 전표 유무와 무관하게 받도록 고쳤는데
**판정 근거 기록은 전표가 있는 경우에만** 남겼습니다. 그러면 단독 검사는
누가 언제 무엇으로 판정했는지 알 수 없습니다.
"""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStandaloneDecision(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create({"name": "557 포장 시험 품목"})
        cls.Inspection = cls.env["iatf.shipping.inspection"]

    def _standalone(self, **extra):
        values = {
            "product_id": self.product.id,
            "inspector_id": self.env.uid,
            "quantity": 10,
            "visual_result": "pass",
            # 치수 판정도 완결성 검사 대상이다. 빼면 세 시험이 모두 **일반
            # 완결성 오류**에서 멈춰, 근거 기록 검증에 도달하지 못하고
            # 모순 가드 시험은 거짓 양성이 된다 (아스트라 A-53-T01).
            "dimension_result": "pass",
            "packaging_result": "pass",
            "label_result": "pass",
            "result": "pass",
        }
        values.update(extra)
        rec = self.Inspection.create(values)
        self.assertFalse(rec.picking_id, "전표 없는 단독 검사")
        return rec

    def test_standalone_decision_records_snapshot(self):
        rec = self._standalone()
        rec.action_start_inspection()
        rec.action_decide()
        self.assertEqual(rec.state, "decided")
        snapshot = rec.outgoing_decision_snapshot or {}
        self.assertTrue(snapshot, "단독 검사도 판정 근거가 남아야 한다")
        self.assertEqual(snapshot.get("by"), self.env.uid, "판정자")
        self.assertTrue(snapshot.get("at"), "판정 시각")
        self.assertTrue(snapshot.get("standalone"), "전표 없는 검사로 표시")
        self.assertEqual(rec.outgoing_decided_by_id, self.env.user)
        self.assertTrue(rec.outgoing_decided_at)

    def test_standalone_still_needs_completeness(self):
        """근거를 남기는 것과 완결성 검사는 별개다 (정상 대조).

        거부 시험은 **목표 조건 하나만** 바꾸고 오류 원인까지 확인한다.
        그러지 않으면 다른 준비값 누락으로 멈춰도 통과한다.
        """
        for field in ("label_result", "dimension_result", "packaging_result"):
            rec = self._standalone(**{field: False})
            rec.action_start_inspection()
            with self.assertRaisesRegex(UserError, "항목 판정이 필요합니다"):
                rec.action_decide()
            self.assertFalse(rec.outgoing_decision_snapshot,
                             "거부된 판정은 근거를 남기지 않는다")
            self.assertNotEqual(rec.state, "decided")

    def test_standalone_fail_with_pass_item_rejected(self):
        rec = self._standalone(visual_result="fail")
        rec.action_start_inspection()
        with self.assertRaisesRegex(UserError, "합격으로 판정할 수 없습니다"):
            rec.action_decide()
