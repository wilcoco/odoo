"""[R144 정책 #9/#12] 검사 기준 마스터를 한 번 넣으면 수입검사가 항목·샘플링 기준·샘플 수량·Ac/Re 를 물려받는다."""
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "r144")
class TestR144CriteriaAutoload(TransactionCase):

    def test_incoming_inspection_inherits_criteria_master(self):
        product = self.env["product.product"].create({"name": "R144-수지", "type": "consu"})
        vendor = self.env["res.partner"].create({"name": "R144-공급사", "supplier_rank": 1})
        other = self.env["res.partner"].create({"name": "R144-다른공급사", "supplier_rank": 1})
        Crit = self.env["iatf.inspection.criteria"]
        Crit.create({"product_id": product.id, "characteristic_name": "수분 함량", "characteristic_type": "material",
                     "specification": "≤0.1%", "measurement_method": "수분계", "sampling_plan": "AQL 0.65 Level II",
                     "sample_size": 5, "accept_number": 0, "reject_number": 1})
        Crit.create({"product_id": product.id, "characteristic_name": "외관(이물)", "characteristic_type": "visual",
                     "specification": "이물 없음", "sequence": 20})
        Crit.create({"product_id": product.id, "supplier_id": other.id, "characteristic_name": "다른 업체 전용",
                     "specification": "해당 없음"})
        iqc = self.env["iatf.incoming.inspection"].create({
            "product_id": product.id, "supplier_id": vendor.id, "quantity_received": 100.0, "quantity_inspected": 5.0})
        self.assertEqual(iqc.line_ids.mapped("characteristic_name"), ["수분 함량", "외관(이물)"],
                         "공통 기준 2건만 적재돼야 한다(다른 업체 전용 제외)")
        self.assertEqual(iqc.line_ids[0].specification, "≤0.1%")
        self.assertEqual((iqc.sampling_plan, iqc.sample_size, iqc.accept_number, iqc.reject_number),
                         ("AQL 0.65 Level II", 5, 0, 1))
        # 이미 항목이 있는 검사엔 손대지 않는다
        iqc2 = self.env["iatf.incoming.inspection"].create({
            "product_id": product.id, "supplier_id": vendor.id, "quantity_received": 1.0, "quantity_inspected": 1.0,
            "line_ids": [(0, 0, {"characteristic_name": "수기 항목", "specification": "x"})]})
        self.assertEqual(iqc2.line_ids.mapped("characteristic_name"), ["수기 항목"])
