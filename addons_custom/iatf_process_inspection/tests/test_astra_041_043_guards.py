"""아스트라 041·043 회귀 — 판정 근거 범위와 자동 부적합 수량 기준.

- A-53-S02: 557 §2 로 **근거 기록**을 전표 없는 검사까지 넓혔는데 **검증**은
  출하 전용 계약을 모든 근거 보유 레코드에 적용해, 일반 공정검사가 방금 수락한
  판정이 만든 근거를 다음 쓰기에서 거부했다(= 종료 불가).
- A-62-S02: 자동 부적합의 영향 수량에 샘플링 **표본 수**를 넣어, 기준을 갖춘
  로트 불합격 처분이 부적합의 `불합격 <= 영향` 과 모순되어 막혔다.
"""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestAstraDecisionScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.product = cls.env["product.product"].create({
            "name": "041 시험 품목", "is_storable": True,
        })
        cls.PQC = cls.env["iatf.process.inspection"]
        cls.other = new_test_user(
            cls.env, login="astra041_inspector", groups="base.group_user")

    def _pqc(self, **values):
        data = dict(
            product_id=self.product.id, company_id=self.company.id,
            inspection_type="full", quantity_produced=10,
            quantity_inspected=10, quantity_accepted=10, quantity_rejected=0,
            inspector_id=self.env.uid, result="pass",
            line_ids=[Command.create({
                "characteristic_name": "외관", "characteristic_type": "visual",
                "specification": "흠 없음", "measured_value": "양호",
                "result": "pass",
            })])
        data.update(values)
        return self.PQC.create(data)

    # ── A-53-S02 ────────────────────────────────────────────────
    def test_general_pqc_can_close_after_decision_by_other_user(self):
        """검사원이 로그인 사용자와 달라도 판정을 수락했으면 종료된다."""
        rec = self._pqc(inspector_id=self.other.id)
        rec.action_start_inspection()
        rec.action_decide()
        self.assertEqual(rec.state, "decided")
        rec.action_close()
        self.assertEqual(rec.state, "closed",
                         "수락한 판정이 만든 근거로 종료가 막히면 안 된다")

    def test_general_pqc_gets_no_outgoing_basis(self):
        """557 §2 의 대상은 **포장검사**다 — 일반 공정검사에 근거를 남기지 않는다.

        남기면 그 근거의 payload 동결이 `notes` 같은 정상 후속 입력을 전부
        거부한다(CI 4건의 원인). 출하 흐름의 "판정 뒤 동결" 계약을 일반
        공정검사에 끌어오지 않는다.
        """
        rec = self._pqc(inspector_id=self.other.id)
        rec.action_start_inspection()
        rec.action_decide()
        self.assertFalse(rec.outgoing_decision_snapshot,
                         "일반 공정검사는 출하 판정 근거 대상이 아니다")
        rec.notes = "판정 뒤에 덧붙인 설명"
        self.assertEqual(rec.notes, "판정 뒤에 덧붙인 설명",
                         "정상 후속 입력이 막히면 안 된다")

    def test_forged_basis_still_rejected(self):
        """근거가 있는 레코드라면 위조는 그대로 걸린다."""
        rec = self._pqc()
        rec.action_start_inspection()
        rec.action_decide()
        self.env.cr.execute(
            "UPDATE iatf_process_inspection SET outgoing_decision_snapshot = %s "
            "WHERE id = %s", ('{"version": 1, "by": 1}', rec.id))
        rec.invalidate_recordset(["outgoing_decision_snapshot"])
        with self.assertRaisesRegex(UserError, "이 검사의 것이 아닙니다"):
            rec.action_close()

    def test_decider_policy_refuses_at_decision_time(self):
        """금지하는 정책이면 **판정할 때** 이유를 알려 거부한다."""
        self.env["ir.config_parameter"].sudo().set_param(
            "quality.pqc_decider_must_be_inspector", "1")
        rec = self._pqc(inspector_id=self.other.id)
        rec.action_start_inspection()
        with self.assertRaisesRegex(UserError, "검사자 본인만"):
            rec.action_decide()
        self.assertNotEqual(rec.state, "decided")
        self.assertFalse(rec.outgoing_decision_snapshot)
        mine = self._pqc(inspector_id=self.env.uid)
        mine.action_start_inspection()
        mine.action_decide()
        self.assertEqual(mine.state, "decided", "본인 판정은 그대로 통과")

    # ── A-62-S02 ────────────────────────────────────────────────
    def test_sampling_fail_creates_nc_with_lot_scope(self):
        rec = self._pqc(
            inspection_type="sampling", quantity_produced=100,
            quantity_inspected=5, quantity_accepted=0, quantity_rejected=100,
            result="fail", sampling_plan="회사 표본계획", sample_size=5,
            accept_number=0,
            line_ids=[Command.create({
                "characteristic_name": "치수1", "characteristic_type": "dimensional",
                "specification": "10±0.1", "measured_value": "10.9",
                "result": "fail"})])
        rec.action_start_inspection()
        rec.action_decide()
        nc = rec.nonconformity_id
        self.assertTrue(nc, "불합격 판정은 부적합을 자동 생성한다")
        self.assertEqual(nc.quantity_affected, 100,
                         "샘플링의 영향 범위는 표본이 아니라 처분 로트다")
        self.assertEqual(nc.quantity_rejected, 100)

    def test_full_inspection_nc_keeps_inspected_basis(self):
        rec = self._pqc(
            inspection_type="full", quantity_produced=10, quantity_inspected=10,
            quantity_accepted=0, quantity_rejected=10, result="fail",
            line_ids=[Command.create({
                "characteristic_name": "치수1", "characteristic_type": "dimensional",
                "specification": "10±0.1", "measured_value": "10.9",
                "result": "fail"})])
        rec.action_start_inspection()
        rec.action_decide()
        self.assertEqual(rec.nonconformity_id.quantity_affected, 10,
                         "전수는 검사한 수량이 곧 처분 범위다")
