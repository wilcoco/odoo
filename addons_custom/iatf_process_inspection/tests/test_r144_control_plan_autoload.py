"""[R144 정책 #9] 승인된 관리계획서가 있으면 공정검사 생성 시 검사 항목이 자동 적재된다."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "r144")
class TestR144ControlPlanAutoload(TransactionCase):

    def test_process_inspection_inherits_approved_control_plan(self):
        if "iatf.control.plan" not in self.env:
            self.skipTest("관리계획서 모듈 없음")
        product = self.env["product.product"].create({"name": "R144-사출품", "type": "consu"})
        if "quality_stage" in self.env["iatf.control.plan.line"]._fields:
            # 단계별 품질 관문(iatf_quality_precedence) 설치 시 승인 관리계획은 회사·제품·BOM 단위이며 단계별 항목·시료·주기·대응계획·
            # MO별 검사 수량과 작성자와 다른 결재자를 요구한다 — 공용 합성 관리계획 헬퍼로 승인본을 만든다(상속 단언은 동일)
            from odoo.addons.injection_worksite.tests.common import InjectionSyntheticControlPlan
            InjectionSyntheticControlPlan.env = self.env
            bom = self.env["mrp.bom"].create({"product_tmpl_id": product.product_tmpl_id.id, "product_qty": 1})
            cp = InjectionSyntheticControlPlan._approve_synthetic_control_plan(product, bom)
        else:
            cp = self.env["iatf.control.plan"].create({
                "title": "R144 사출품 관리계획서(합성)", "product_id": product.id,
                "line_ids": [(0, 0, {"characteristic_name": "두께", "characteristic_type": "product",
                                     "specification": "3.0±0.1mm", "evaluation_method": "버니어"}),
                             (0, 0, {"characteristic_name": "외관 버리", "characteristic_type": "product",
                                     "specification": "버리 없음", "evaluation_method": "육안", "sequence": 20})]})
            cp.action_submit_review(); cp.action_approve()
        self.assertEqual(cp.state, "approved")
        ins = self.env["iatf.process.inspection"].create({"product_id": product.id, "quantity_inspected": 1.0})
        self.assertEqual(ins.control_plan_id, cp)
        if "quality_stage" in self.env["iatf.control.plan.line"]._fields:
            self.assertEqual(ins.line_ids.mapped("characteristic_name"), cp.line_ids.mapped("characteristic_name"))
            self.assertEqual(ins.line_ids[0].specification, cp.line_ids[0].specification)
        else:
            self.assertEqual(ins.line_ids.mapped("characteristic_name"), ["두께", "외관 버리"])
            self.assertEqual(ins.line_ids[0].specification, "3.0±0.1mm")
