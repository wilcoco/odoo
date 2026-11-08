"""아스트라 042 (A-62-S01) — 수량 모순 건의 단계 전환 재검사.

573 §3 은 원인분석·시정조치·종결에서 수량 관계를 **다시** 보고, 기존 모순 건을
소급 변경 없이 보고하도록 한다. `_check_quantities` 는 `@api.constrains` 이므로
수량 필드를 쓸 때만 불린다. 그래서 제약 도입 **전에** 저장된 모순 건은 수량을
건드리지 않는 단계 전환 버튼으로 그대로 종결까지 간다.

제약 도입 전 자료를 시험에서 만들려면 ORM 을 지나야 하므로 SQL 로 컬럼만
바꾼다. 업무 수량을 지어내는 것이 아니라 **기존 모순 상태를 재현**한다.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestQuantityStageRecheck(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create({"name": "042 시험 품목"})
        cls.NC = cls.env["iatf.nonconformity"]

    def _nc(self, affected=10.0, rejected=3.0):
        nc = self.NC.create({
            "title": "042 시험 부적합",
            "nc_type": "process",
            "severity": "major",
            "product_id": self.product.id,
            "company_id": self.env.company.id,
            "problem_description": "<p>시험용 기록</p>",
            "containment_action": "<p>격리 완료</p>",
            "root_cause": "<p>원인 확인</p>",
            "quantity_affected": affected,
            "quantity_rejected": rejected,
        })
        return nc

    def _force_quantities(self, nc, affected, rejected):
        """제약 도입 전에 저장된 모순 값을 재현한다(ORM 우회는 시험 한정)."""
        self.env.cr.execute(
            "UPDATE iatf_nonconformity SET quantity_affected = %s, "
            "quantity_rejected = %s WHERE id = %s", (affected, rejected, nc.id))
        nc.invalidate_recordset(["quantity_affected", "quantity_rejected"])
        return nc

    def test_save_constraint_still_rejects(self):
        with self.assertRaises(ValidationError):
            self._nc(affected=1.0, rejected=2.0)
        with self.assertRaises(ValidationError):
            self._nc(affected=-1.0, rejected=0.0)

    def test_legacy_contradiction_blocks_stage_transitions(self):
        for method in ("action_start_analysis", "action_start_corrective",
                       "action_close"):
            nc = self._force_quantities(self._nc(), 1.0, 2.0)
            with self.assertRaisesRegex(UserError, "수량을 바로잡"):
                getattr(nc, method)()
            self.assertNotEqual(nc.state, "closed")
            # 소급 변경 금지: 거부가 값을 고치지 않는다.
            self.assertEqual(nc.quantity_affected, 1.0)
            self.assertEqual(nc.quantity_rejected, 2.0)

    def test_normal_quantities_pass_stage_transitions(self):
        nc = self._nc(affected=10.0, rejected=3.0)
        nc.action_start_analysis()
        self.assertEqual(nc.state, "analysis")
        nc.action_start_corrective()
        self.assertEqual(nc.state, "corrective")

    def test_zero_quantities_pass(self):
        nc = self._nc(affected=0.0, rejected=0.0)
        nc.action_start_analysis()
        self.assertEqual(nc.state, "analysis")
