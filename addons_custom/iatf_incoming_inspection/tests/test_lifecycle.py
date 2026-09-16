from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestIqcLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({'name': 'Phase3 quality', 'is_storable': True, 'tracking': 'lot'})
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.env.company.id)], limit=1)
        cls.supplier = cls.env['res.partner'].create({'name': 'Phase3 supplier', 'supplier_rank': 1})
        cls.lots = cls.env['stock.lot'].create([{'name': 'PHASE3-'+str(i), 'product_id': cls.product.id,
                                             'company_id': cls.env.company.id} for i in range(2)])
        groups = 'stock.group_stock_user,iatf_incoming_inspection.group_incoming_inspection_user'
        cls.inspector = new_test_user(cls.env, login='phase3_inspector', groups=groups)
        cls.stock = new_test_user(cls.env, login='phase3_stock', groups='stock.group_stock_user')
        cls.reviewer = new_test_user(cls.env, login='phase3_reviewer', groups=groups+',iatf_incoming_inspection.group_quality_release_reviewer')
        cls.approver = new_test_user(cls.env, login='phase3_approver', groups='iatf_incoming_inspection.group_quality_release_approver')
        cls.executor = new_test_user(cls.env, login='phase3_executor', groups='iatf_incoming_inspection.group_quality_release_executor')

    def _receipt(self, quantities=(4, 6), uom=None, demand=None, stock_user=False, route='picking'):
        uom = uom or self.product.uom_id
        pick = self.env['stock.picking'].create({'picking_type_id': self.wh.in_type_id.id,
            'partner_id': self.supplier.id, 'location_id': self.env.ref('stock.stock_location_suppliers').id,
            'location_dest_id': self.wh.lot_stock_id.id})
        move = self.env['stock.move'].create({'name': 'Phase3 receipt', 'picking_id': pick.id,
            'product_id': self.product.id, 'product_uom': uom.id, 'product_uom_qty': demand or sum(quantities),
            'location_id': pick.location_id.id, 'location_dest_id': pick.location_dest_id.id})
        pick.action_confirm()
        move.move_line_ids.unlink()
        for lot, quantity in zip(self.lots, quantities):
            self.env['stock.move.line'].create({'move_id': move.id, 'product_id': self.product.id,
                'product_uom_id': uom.id, 'lot_id': lot.id, 'quantity': quantity, 'picked': True,
                'location_id': pick.location_id.id, 'location_dest_id': pick.location_dest_id.id})
        move.picked = True
        actor = pick.with_user(self.stock) if stock_user else pick
        if route == 'wizard':
            action = actor.with_context(skip_sms=True).button_validate()
            self.assertEqual(action['res_model'], 'stock.backorder.confirmation')
            self.env[action['res_model']].with_context(action['context']).create({'pick_ids': [(6, 0, pick.ids)]}).process()
        elif route == 'move':
            move._action_done()
        else:
            actor.with_context(skip_sms=True, cancel_backorder=bool(demand))._action_done()
        return pick

    def _pass(self, iqc):
        iqc = iqc.with_user(self.inspector)
        iqc.write({'result': 'pass', 'disposition': 'accept'})
        iqc.action_decide()
        return iqc

    def _exception(self):
        lot = self.lots[0]
        lot.write({'quality_hold': True, 'hold_reason': 'New manual review'})
        iqc = self.env['iatf.incoming.inspection'].with_user(self.inspector).create({
            'supplier_id': self.supplier.id, 'product_id': self.product.id, 'lot_id': lot.id,
            'quantity_received': 10, 'quantity_inspected': 10, 'result': 'pass', 'disposition': 'accept'})
        iqc.action_decide()
        iqc.write({'release_reviewer_id': self.reviewer.id, 'release_approver_id': self.approver.id,
                   'release_executor_id': self.executor.id, 'release_reason': 'Verified evidence for current hold'})
        return iqc

    def _approve(self, iqc):
        iqc.action_request_release()
        iqc.with_user(self.reviewer).action_approve_approval()
        iqc.with_user(self.approver).action_approve_approval()

    def test_receipt_generates_actual_lot_quantities_and_is_idempotent(self):
        pick = self._receipt(stock_user=True)
        rows = pick.iqc_inspection_ids.sorted('lot_id')
        self.assertEqual(rows.mapped('quantity_received'), [4, 6])
        self.assertEqual(rows.lot_id, self.lots)
        versions = self.lots.mapped('hold_version')
        pick._create_iqc_inspections()
        self.assertEqual(len(pick.iqc_inspection_ids), 2)
        self.assertEqual(self.lots.mapped('hold_version'), versions)
        self._pass(rows[0])
        self.assertFalse(self.lots[0].quality_hold)
        self.assertTrue(self.lots[1].quality_hold)
        self._pass(rows[1])
        self.assertFalse(any(self.lots.mapped('quality_hold')))

    def test_receipt_uom_conversion_and_partial_quantity(self):
        pick = self._receipt((1, 2), uom=self.env.ref('uom.product_uom_dozen'), demand=4)
        self.assertEqual(sorted(pick.iqc_inspection_ids.mapped('quantity_received')), [12, 24])
        self.assertEqual(sum(pick.iqc_inspection_ids.mapped('quantity_received')), 36)

    def _supplier_return(self, picking):
        wizard = self.env['stock.return.picking'].with_context(active_model='stock.picking', active_id=picking.id).create({'picking_id': picking.id})
        wizard.product_return_moves.quantity = 1
        action = wizard.action_create_returns()
        returned = self.env['stock.picking'].browse(action['res_id'])
        returned.move_ids.move_line_ids.unlink()
        move = returned.move_ids
        self.env['stock.move.line'].create({'move_id': move.id, 'product_id': self.product.id,
            'product_uom_id': self.product.uom_id.id, 'lot_id': self.lots[0].id,
            'quantity': 1, 'picked': True, 'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id})
        move.picked = True
        return returned

    def test_standard_supplier_return_keeps_hold_and_needs_no_customer_oqc(self):
        pick = self._receipt((4,))
        returned = self._supplier_return(pick)
        returned.with_context(skip_sms=True).button_validate()
        self.assertEqual(returned.state, 'done')
        self.assertFalse(returned.oqc_inspection_ids)
        self.assertTrue(self.lots[0].quality_hold)

    def test_standard_return_is_reused_as_iqc_disposition_without_duplicate(self):
        pick = self._receipt((4,))
        iqc = pick.iqc_inspection_ids
        iqc.write({'result': 'conditional', 'disposition': 'return', 'quantity_accepted': 3, 'quantity_rejected': 1})
        iqc.action_decide()
        returned = self._supplier_return(pick)
        returned.with_context(skip_sms=True).button_validate()
        count = self.env['stock.move'].search_count([('origin_returned_move_id', '=', iqc.source_move_id.id)])
        iqc.action_process_disposition()
        self.assertEqual(iqc.disposal_move_id, returned.move_ids)
        self.assertEqual(self.env['stock.move'].search_count([('origin_returned_move_id', '=', iqc.source_move_id.id)]), count)
        self.assertTrue(iqc._quantity_resolved())

    def test_supplier_return_rejects_wrong_lot_and_excess_cumulative_quantity(self):
        pick = self._receipt((4,))
        returned = self._supplier_return(pick)
        line = returned.move_ids.move_line_ids
        line.lot_id = self.lots[1]
        with self.assertRaises(UserError), self.cr.savepoint():
            returned._action_done()
        line.write({'lot_id': self.lots[0].id, 'quantity': 5})
        with self.assertRaises(UserError), self.cr.savepoint():
            returned._action_done()
        line.quantity = 3
        returned.move_ids.product_uom_qty = 3
        returned.with_context(skip_sms=True).button_validate()
        self.assertEqual(returned.state, 'done')
        another = self._supplier_return(pick)
        another.move_ids.move_line_ids.quantity = 2
        with self.assertRaises(UserError), self.cr.savepoint():
            another._action_done()

    def test_old_decision_cannot_release_new_hold_or_changed_reason(self):
        iqc = self._pass(self._receipt().iqc_inspection_ids[0])
        old = iqc.hold_version
        iqc.lot_id.write({'quality_hold': True, 'hold_reason': 'New defect'})
        self.assertGreater(iqc.lot_id.hold_version, old)
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.action_decide()
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.lot_id._release_quality_hold_from_iqc(iqc)
        self.assertTrue(iqc.lot_id.quality_hold)

    def test_partial_or_sort_verdict_keeps_whole_lot_held(self):
        iqc = self._receipt().iqc_inspection_ids.filtered(lambda r: r.lot_id == self.lots[0])
        iqc.write({'result': 'conditional', 'disposition': 'sort', 'quantity_accepted': 3, 'quantity_rejected': 1})
        iqc.action_decide()
        self.assertTrue(iqc.lot_id.quality_hold)
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc._release_quality_hold()

    def test_failed_decision_does_not_move_other_stock_to_scrap(self):
        pick = self._receipt()
        iqc = pick.iqc_inspection_ids.filtered(lambda r: r.lot_id == self.lots[0])
        self.env['stock.quant']._update_available_quantity(self.product, self.wh.lot_stock_id, 8, lot_id=self.lots[1])
        before = self.env['stock.move'].search_count([('product_id', '=', self.product.id), ('state', '=', 'done')])
        iqc.write({'result': 'fail', 'disposition': 'return'})
        iqc.action_decide()
        self.assertEqual(self.env['stock.move'].search_count([('product_id', '=', self.product.id), ('state', '=', 'done')]), before)
        self.assertTrue(iqc.lot_id.quality_hold)

    def test_return_only_rejected_lot_quantity_and_repeat_is_idempotent(self):
        pick = self._receipt()
        iqc = pick.iqc_inspection_ids.filtered(lambda r: r.lot_id == self.lots[0])
        iqc.write({'result': 'conditional', 'disposition': 'return', 'quantity_accepted': 3, 'quantity_rejected': 1})
        iqc.action_decide()
        iqc.action_process_disposition()
        move = iqc.disposal_move_id
        self.assertEqual(move.state, 'done')
        self.assertEqual(move.quantity, 1)
        self.assertEqual(move.move_line_ids.lot_id, self.lots[0])
        self.assertEqual(move.origin_returned_move_id, iqc.source_move_id)
        iqc.action_process_disposition()
        self.assertEqual(iqc.disposal_move_id, move)
        self.assertEqual(self.env['stock.quant']._get_available_quantity(self.product, self.wh.lot_stock_id, lot_id=self.lots[1]), 6)
        iqc = iqc.with_user(self.inspector)
        iqc.write({'release_reviewer_id': self.reviewer.id, 'release_approver_id': self.approver.id,
                   'release_executor_id': self.executor.id, 'release_reason': 'Rejected quantity returned'})
        self._approve(iqc)
        iqc.with_user(self.executor).action_release_hold()
        self.assertFalse(self.lots[0].quality_hold)
        self.assertTrue(self.lots[1].quality_hold)

    def test_scrap_only_rejected_quantity(self):
        iqc = self._receipt().iqc_inspection_ids.filtered(lambda r: r.lot_id == self.lots[0])
        iqc.write({'result': 'fail', 'disposition': 'scrap'})
        iqc.action_decide()
        iqc.action_process_disposition()
        self.assertEqual(iqc.disposal_move_id.quantity, 4)
        self.assertTrue(iqc.disposal_move_id.location_dest_id.scrap_location)
        self.assertEqual(iqc.disposal_move_id.move_line_ids.lot_id, self.lots[0])

    def test_distinct_approvers_then_designated_executor(self):
        iqc = self._exception()
        self.assertTrue(iqc.lot_id.quality_hold)
        iqc.action_request_release()
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.with_user(self.approver).action_approve_approval()
        iqc.with_user(self.reviewer).action_approve_approval()
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.with_user(self.executor).action_release_hold()
        iqc.with_user(self.approver).action_approve_approval()
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.with_user(self.inspector).action_release_hold()
        iqc.with_user(self.executor).action_release_hold()
        self.assertFalse(iqc.lot_id.quality_hold)
        self.assertEqual(iqc.released_by, self.executor)
        iqc.with_user(self.executor).action_release_hold()

    def test_same_person_or_wrong_role_cannot_satisfy_two_steps(self):
        iqc = self._exception()
        iqc.release_approver_id = self.reviewer
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.action_request_release()
        iqc.release_approver_id = self.inspector
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.action_request_release()

    def test_production_approver_role_does_not_edit_inspection(self):
        iqc = self._exception()
        with self.assertRaises(AccessError), self.cr.savepoint():
            iqc.with_user(self.approver).write({'quantity_accepted': 999})
        self._approve(iqc)
        iqc.with_user(self.executor).action_release_hold()
        self.assertFalse(iqc.lot_id.quality_hold)

    def test_hold_after_approval_or_role_revocation_blocks_execution(self):
        iqc = self._exception()
        self._approve(iqc)
        iqc.lot_id.hold_reason = 'Changed risk'
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.with_user(self.executor).action_release_hold()
        self.assertTrue(iqc.lot_id.quality_hold)

    def test_detail_change_reholds_and_invalidates_decision(self):
        iqc = self._pass(self._receipt().iqc_inspection_ids[0])
        old = iqc.decision_snapshot
        self.env['iatf.incoming.inspection.line'].create({'inspection_id': iqc.id, 'characteristic_name': 'New result', 'result': 'fail'})
        self.assertTrue(iqc.lot_id.quality_hold)
        self.assertFalse(iqc.decision_snapshot)
        self.assertEqual(iqc.state, 'inspecting')
        self.assertTrue(old)
        self.assertEqual(iqc.decision_history[-1]['evidence'], old)

    def test_quality_only_role_can_decide_without_inventory_write(self):
        user = new_test_user(self.env, login='phase3_quality_only', groups='iatf_incoming_inspection.group_incoming_inspection_user')
        iqc = self._receipt().iqc_inspection_ids[0].with_user(user)
        iqc.write({'result': 'pass', 'disposition': 'accept'})
        iqc.action_decide()
        self.assertFalse(iqc.lot_id.quality_hold)
        with self.assertRaises(AccessError), self.cr.savepoint():
            iqc.lot_id.write({'quality_hold': True})

    def test_internal_move_completion_also_creates_iqc(self):
        pick = self._receipt(route='move')
        self.assertEqual(len(pick.iqc_inspection_ids), 2)
        self.assertTrue(all(self.lots.mapped('quality_hold')))

    def test_receipt_backorder_wizard_generates_only_done_lot_quantity(self):
        pick = self._receipt((4,), demand=10, route='wizard')
        self.assertEqual(pick.iqc_inspection_ids.quantity_received, 4)
        backorder = self.env['stock.picking'].search([('backorder_id', '=', pick.id)])
        self.assertEqual(len(backorder), 1)
        self.assertFalse(backorder.iqc_inspection_ids)
        self.assertEqual(backorder.move_ids.product_uom_qty, 6)

    def test_approval_role_revocation_blocks_final_release(self):
        iqc = self._exception()
        self._approve(iqc)
        self.reviewer.groups_id = [(3, self.env.ref('iatf_incoming_inspection.group_quality_release_reviewer').id)]
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.with_user(self.executor).action_release_hold()
        self.assertTrue(iqc.lot_id.quality_hold)

    def test_changed_attachment_evidence_blocks_released_lot_usage(self):
        iqc = self._receipt().iqc_inspection_ids[0]
        attachment = self.env['ir.attachment'].create({'name': 'Phase3 certificate', 'type': 'binary', 'datas': 'b2xk', 'res_model': iqc._name, 'res_id': iqc.id})
        iqc.attachment_ids = attachment
        self._pass(iqc)
        attachment.datas = 'bmV3'
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.lot_id._check_quality_usable()

    def test_quantity_scope_state_and_context_forgery_rejected(self):
        iqc = self._receipt().iqc_inspection_ids[0]
        for vals in ({'state': 'decided'}, {'hold_version': 999}, {'released_version': 999}, {'source_move_id': False}, {'quantity_received': 999}):
            with self.assertRaises(UserError), self.cr.savepoint():
                iqc.with_context(_iqc_lifecycle=True).write(vals)
        for vals in ({'hold_version': 0}, {'hold_origin': 'iqc'}, {'quality_hold': False}):
            with self.assertRaises(AccessError), self.cr.savepoint():
                iqc.lot_id.with_context(_iqc_release=True).write(vals)

    def test_pending_second_receipt_cannot_be_released_by_first(self):
        first = self._receipt((4,)).iqc_inspection_ids
        self._receipt((2,))
        first.action_start_inspection()
        first.result = 'pass'
        first.action_decide()
        self.assertTrue(self.lots[0].quality_hold)

    def test_approval_line_replacement_cannot_remove_second_step(self):
        iqc = self._exception()
        iqc.action_request_release()
        iqc.action_reset_approval()
        iqc.approval_line_ids[-1].unlink()
        with self.assertRaises(UserError), self.cr.savepoint():
            iqc.action_submit_approval()

    def test_company_boundary(self):
        other = self.env['res.company'].create({'name': 'Phase3 other company'})
        iqc = self.env['iatf.incoming.inspection'].with_company(other).create({
            'company_id': other.id, 'supplier_id': self.supplier.id, 'product_id': self.product.id,
            'quantity_received': 1, 'quantity_inspected': 1})
        with self.assertRaises(AccessError), self.cr.savepoint():
            iqc.with_user(self.inspector).with_context(allowed_company_ids=[self.env.company.id]).write({'result': 'pass'})
