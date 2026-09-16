from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestIqcReleaseGuard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_user = new_test_user(cls.env, login="phase1_stock", groups="stock.group_stock_user")
        cls.inspector = new_test_user(cls.env, login="phase1_iqc", groups="stock.group_stock_user,iatf_incoming_inspection.group_incoming_inspection_user")
        cls.product = cls.env["product.product"].create({"name": "Phase1 IQC", "is_storable": True, "tracking": "lot"})
        cls.lot = cls.env["stock.lot"].create({"name": "PHASE1-IQC", "product_id": cls.product.id, "company_id": cls.env.company.id, "quality_hold": True})

    def _inspection(self, result="pass", product=None):
        return self.env["iatf.incoming.inspection"].with_user(self.inspector).create({
            "supplier_id": self.env.company.partner_id.id, "product_id": (product or self.product).id,
            "lot_id": self.lot.id, "quantity_received": 1, "quantity_inspected": 1, "result": result,
        })

    def test_direct_and_client_context_release_are_rejected(self):
        for context in ({}, {"_iqc_release": True}, {"_iqc_release": [True, self.lot.ids]}, {"skip_quality_hold": True}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                self.lot.with_user(self.stock_user).with_context(**context).write({"quality_hold": False})
            self.assertTrue(self.lot.quality_hold)

    def test_normal_iqc_decision_releases_only_matching_lot(self):
        inspection = self._inspection()
        inspection.action_decide()
        self.assertEqual(inspection.state, "decided")
        self.assertFalse(self.lot.quality_hold)
        inspection.action_decide()
        self.assertFalse(self.lot.quality_hold)

    def test_failed_or_unfinished_inspection_cannot_release(self):
        for result, state in (("pass", "draft"), ("fail", "decided")):
            inspection = self._inspection(result)
            inspection.state = state
            with self.assertRaises(UserError), self.cr.savepoint():
                self.lot._release_quality_hold_from_iqc(inspection)
            self.assertTrue(self.lot.quality_hold)

    def test_wrong_product_cannot_release(self):
        other = self.env["product.product"].create({"name": "Other IQC product", "is_storable": True})
        self.assertTrue(self.lot.quality_hold)
        self.assertNotEqual(other, self.lot.product_id)
        inspection = self._inspection(product=other)
        self.assertEqual(inspection.product_id, other)
        self.assertEqual(inspection.lot_id, self.lot)
        with self.assertRaises(UserError), self.cr.savepoint():
            inspection.action_decide()
        self.assertTrue(self.lot.quality_hold)

    def test_setting_hold_and_editing_lot_name_remain_available(self):
        self.lot.with_user(self.stock_user).write({"quality_hold": True, "hold_reason": "Recheck", "name": "PHASE1-RENAMED"})
        self.assertTrue(self.lot.quality_hold)
        self.assertEqual(self.lot.hold_reason, "Recheck")
