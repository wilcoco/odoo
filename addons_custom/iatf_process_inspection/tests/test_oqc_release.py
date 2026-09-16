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

    def test_cancelled_inspection_requires_replacement_and_does_not_block_it(self):
        picking, old = self._picking(approve=True)
        old.action_cancel()
        action = picking.with_user(self.stock_user).button_validate()
        self.assertEqual(action['tag'], 'display_notification')
        current = picking.oqc_inspection_ids - old
        self.assertEqual(len(current), 1)
        with self.assertRaises(UserError), self.cr.savepoint():
            picking._action_done()
        current.write({'state': 'decided', 'result': 'pass', 'disposition': 'ship',
                       'approval_line_ids': [(0, 0, {'user_id': self.env.uid})]})
        current.action_submit_approval()
        current.action_approve_approval()
        picking.with_context(skip_sms=True).button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(old.state, 'cancelled')

    def test_partial_shipping_backorder_requires_its_own_inspection(self):
        picking, inspection = self._picking(approve=True)
        picking.move_ids.product_uom_qty = 2
        action = picking.with_context(skip_sms=True).button_validate()
        self.assertEqual(action['res_model'], 'stock.backorder.confirmation')
        wizard = self.env[action['res_model']].with_context(action['context']).create({
            'pick_ids': [(6, 0, picking.ids)]})
        wizard.process()
        self.assertEqual(picking.state, 'done')
        backorder = self.env['stock.picking'].search([('backorder_id', '=', picking.id)])
        self.assertEqual(len(backorder), 1)
        self.assertFalse(backorder.oqc_inspection_ids)
        with self.assertRaises(UserError), self.cr.savepoint():
            backorder._action_done()
        self.env['stock.quant']._update_available_quantity(self.product, self.warehouse.lot_stock_id, 1)
        backorder.action_assign()
        backorder.move_ids.move_line_ids.write({'quantity': 1, 'picked': True})
        backorder.with_context(skip_sms=True).button_validate()
        oqc = backorder.oqc_inspection_ids
        oqc.write({'state': 'decided', 'result': 'pass', 'disposition': 'ship',
                   'approval_line_ids': [(0, 0, {'user_id': self.env.uid})]})
        oqc.action_submit_approval()
        oqc.action_approve_approval()
        backorder.with_context(skip_sms=True).button_validate()
        self.assertEqual(backorder.state, 'done')

    def test_detail_changes_require_new_approval_and_preserve_old_values(self):
        picking, inspection = self._picking()
        line = self.env['iatf.process.inspection.line'].create({
            'inspection_id': inspection.id, 'characteristic_name': 'Length', 'measured_value': '10'})
        inspection.write({'approval_line_ids': [(0, 0, {'user_id': self.env.uid})]})
        inspection.action_submit_approval()
        inspection.action_approve_approval()
        old = inspection.approval_request_id
        line.measured_value = '11'
        self.assertEqual(inspection.approval_state, 'draft')

        self.assertEqual(old.state, 'approved')
        self.assertEqual(old.snapshot['lines'][0]['measured_value'], '10')
        with self.assertRaises(UserError), self.cr.savepoint():
            picking._action_done()
        inspection.action_submit_approval()
        inspection.action_approve_approval()
        line.unlink()
        self.assertEqual(inspection.approval_state, 'draft')
        inspection.action_submit_approval()
        inspection.action_approve_approval()
        self.env['iatf.process.inspection.line'].with_context(default_inspection_id=inspection.id).create({
            'characteristic_name': 'New length', 'measured_value': '12'})
        self.assertEqual(inspection.approval_state, 'draft')

    def test_lot_held_after_oqc_approval_cannot_ship(self):
        picking, inspection = self._picking(approve=True)
        lot = self.env['stock.lot'].create({'name': 'PHASE21-SHIP-HOLD', 'product_id': self.product.id,
                                          'company_id': self.env.company.id})
        picking.move_ids.move_line_ids.lot_id = lot
        picking._check_oqc_release()
        lot.quality_hold = True
        for operation in (picking.button_validate, picking._action_done, picking.move_ids._action_done):
            with self.assertRaises(UserError), self.cr.savepoint():
                operation()
        self.assertEqual(inspection.approval_state, 'approved')
        self.assertNotEqual(picking.state, 'done')
