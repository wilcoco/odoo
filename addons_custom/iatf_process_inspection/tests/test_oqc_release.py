from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestOqcRelease(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.stock_user = new_test_user(cls.env, login="phase1_oqc_stock", groups="stock.group_stock_user")
        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.env.company.id)], limit=1)
        cls.product = cls.env["product.product"].create({"name": "Phase1 OQC", "is_storable": True})

    def _picking(self, result="pass", disposition="ship", approve=False):
        source = self.warehouse.lot_stock_id
        destination = self.env.ref("stock.stock_location_customers")
        self.env["stock.quant"]._update_available_quantity(self.product, source, 1)
        picking = self.env["stock.picking"].create({"picking_type_id": self.warehouse.out_type_id.id, "location_id": source.id, "location_dest_id": destination.id, "partner_id": self.env.company.partner_id.id})
        move = self.env["stock.move"].create({"name": "Phase1 shipment", "picking_id": picking.id, "product_id": self.product.id, "product_uom": self.product.uom_id.id, "product_uom_qty": 1, "location_id": source.id, "location_dest_id": destination.id})
        picking.action_confirm()
        picking.action_assign()
        move.move_line_ids.write({"quantity": 1, "picked": True})
        inspection = self.env["iatf.process.inspection"].create({"inspection_stage": "oqc", "picking_id": picking.id, "product_id": self.product.id, "quantity_inspected": 1, "quantity_produced": 1, "result": result, "disposition": disposition, "state": "decided"})
        if approve:
            request = inspection.approval_request_id
            request.line_ids.unlink()
            request.write({"line_ids": [(0, 0, {"sequence": 1, "user_id": self.env.user.id})]})
            inspection.action_submit_approval()
            inspection.action_approve_approval()
            self.assertEqual(inspection.approval_state, "approved")
        return picking, inspection

    def test_hold_and_non_shipping_disposition_block_all_completion_routes(self):
        for result, disposition in (("hold", "hold"), ("pass", "hold"), ("conditional", "sort")):
            picking, _ = self._picking(result, disposition, approve=True)
            for fn in (lambda: picking.button_validate(), lambda: picking._action_done(), lambda: picking.move_ids._action_done()):
                with self.assertRaises(UserError), self.cr.savepoint():
                    fn()
                self.assertNotEqual(picking.state, "done")

    def test_pass_without_approval_blocks(self):
        picking, _ = self._picking()
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.with_context(skip_sms=True).button_validate()

    def test_approved_normal_shipping_by_stock_user(self):
        picking, _ = self._picking(approve=True)
        # The installed packaging module separately requires packaging access.
        # OQC itself must work with stock access only, without inspection ACLs.
        picking.with_user(self.stock_user)._check_oqc_release()
        packaging_group = self.env.ref("iatf_packaging.group_packaging_user", raise_if_not_found=False)
        if packaging_group:
            self.stock_user.write({"groups_id": [(4, packaging_group.id)]})
        picking.with_user(self.stock_user).with_context(skip_sms=True).button_validate()
        self.assertEqual(picking.state, "done")

    def test_approved_concession_shipping(self):
        picking, _ = self._picking("conditional", "concession", approve=True)
        picking.with_context(skip_sms=True).button_validate()
        self.assertEqual(picking.state, "done")

    def test_missing_inspection_blocks_internal_completion(self):
        picking, inspection = self._picking()
        inspection.unlink()
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.move_ids._action_done()

    def test_first_validation_creates_pending_inspection_without_shipping(self):
        picking, inspection = self._picking()
        inspection.unlink()
        action = picking.with_user(self.stock_user).button_validate()
        self.assertEqual(action["tag"], "display_notification")
        self.assertTrue(picking.oqc_inspection_ids)
        self.assertNotEqual(picking.state, "done")
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.with_user(self.stock_user).button_validate()

    def test_quality_user_can_manage_stock_created_oqc_and_finish_shipment(self):
        inspector = new_test_user(self.env, login='approval_oqc_inspector', groups='iatf_process_inspection.group_process_inspection_user')
        approver = new_test_user(self.env, login='approval_oqc_approver', groups='iatf_process_inspection.group_process_inspection_user')
        picking, inspection = self._picking()
        inspection.unlink()
        picking.with_user(self.stock_user).button_validate()
        inspection = picking.oqc_inspection_ids.with_user(inspector)
        self.assertEqual(inspection.approval_request_id.requester_id, self.stock_user)
        inspection.check_access('write')
        inspection.approval_line_ids.unlink()
        inspection.write({'result': 'pass', 'disposition': 'ship',
                          'approval_line_ids': [(0, 0, {'user_id': approver.id})]})
        inspection.action_decide()
        inspection.action_submit_approval()
        with self.assertRaises(UserError), self.cr.savepoint():
            inspection.action_approve_approval()
        inspection.with_user(approver).action_approve_approval()
        group = self.env.ref('iatf_packaging.group_packaging_user', raise_if_not_found=False)
        if group:
            self.stock_user.write({'groups_id': [(4, group.id)]})
        picking.with_user(self.stock_user).with_context(skip_sms=True).button_validate()
        self.assertEqual(picking.state, 'done')

    def test_unrelated_product_approval_does_not_authorize_shipping(self):
        picking, inspection = self._picking(approve=True)
        inspection.product_id = self.env["product.product"].create({"name": "Unrelated OQC", "is_storable": True})
        with self.assertRaises(UserError), self.cr.savepoint():
            picking.move_ids._action_done()
