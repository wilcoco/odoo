"""MO 생성 확인 위자드의 요약과 실제 생성 대상 정합성 테스트."""

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestGenerateMOWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create({
            "name": "T-MO 요약 사출품",
            "default_code": "T-MO-SUMMARY",
            "type": "consu",
        })
        cls.workcenter = cls.env["mrp.workcenter"].create({
            "name": "T-MO 요약 사출기",
        })
        cls.mold = cls.env["injection.mold"].create({
            "name": "T-MO 요약 금형",
            "code": "T-MO-SUMMARY-MOLD",
            "product_id": cls.product.id,
        })
        cls.plan_run = cls.env["injection.planning.run"].create({
            "plan_date_from": "2026-07-22",
            "plan_date_to": "2026-07-22",
            "state": "review",
        })
        cls.draft_line = cls.env["injection.planning.line"].create({
            "planning_run_id": cls.plan_run.id,
            "plan_date": "2026-07-22",
            "workcenter_id": cls.workcenter.id,
            "mold_id": cls.mold.id,
            "product_id": cls.product.id,
            "planned_qty": 150.0,
            "changeover_needed": True,
            "state": "draft",
        })
        cls.env["injection.planning.line"].create({
            "planning_run_id": cls.plan_run.id,
            "plan_date": "2026-07-22",
            "workcenter_id": cls.workcenter.id,
            "mold_id": cls.mold.id,
            "product_id": cls.product.id,
            "planned_qty": 300.0,
            "changeover_needed": True,
            "state": "confirmed",
        })

    def test_01_summary_recomputes_after_default_run_is_applied(self):
        """빈 위자드가 먼저 계산돼도 계획 선택 후 draft 요약으로 갱신된다."""
        wizard = self.env["injection.generate.mo.wizard"].new({})
        self.assertEqual(wizard.line_count, 0)

        wizard.planning_run_id = self.plan_run

        self.assertEqual(wizard.line_count, 1)
        self.assertAlmostEqual(wizard.total_qty, 150.0)
        self.assertEqual(wizard.changeover_count, 1)

    def test_02_summary_and_generation_share_candidate_lines(self):
        """팝업과 생성 로직은 확정 라인을 제외한 동일 집합을 사용한다."""
        candidates = self.plan_run._get_mo_candidate_lines()
        self.assertEqual(candidates, self.draft_line)

        wizard = self.env["injection.generate.mo.wizard"].new({
            "planning_run_id": self.plan_run.id,
        })
        self.assertEqual(wizard.line_count, len(candidates))
        self.assertAlmostEqual(wizard.total_qty, sum(candidates.mapped("planned_qty")))

    def test_03_empty_candidate_run_is_blocked(self):
        """생성 대상 0건을 정상 확정으로 오인하지 않게 명시적으로 차단한다."""
        empty_run = self.env["injection.planning.run"].create({
            "plan_date_from": "2026-07-22",
            "plan_date_to": "2026-07-22",
            "state": "review",
        })

        with self.assertRaisesRegex(UserError, "MO 생성 대상 계획 라인이 없습니다"):
            empty_run.action_confirm_generate_mo()
        with self.assertRaisesRegex(UserError, "MO 생성 대상 계획 라인이 없습니다"):
            empty_run.generate_manufacturing_orders()
