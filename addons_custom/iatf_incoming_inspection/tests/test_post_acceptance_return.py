"""2026-09-27 사용자 결정 ⑤(v12 후보): 입고검사 합격으로 해제된 재고의 **표준 공급사 반품** 경로.
표준 반품 위저드는 원 입고 이동을 copy() 하는데 iqc_release_location_id(copy=True) 가 실려 IQC 전용 create 가드에
걸려 있었다(T3-c). 완료된 공급자 입고의 복제본은 IQC 원천 표시를 물려받지 않는다. 검사대기 재고 가드는 그대로다."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged, new_test_user
from . import test_iqc_gate as gate_fixture


@tagged('post_install', '-at_install', 'post_acceptance_return')
class TestPostAcceptanceReturn(TransactionCase):
    _receipt = gate_fixture.TestIqcGate._receipt
    _approve = gate_fixture.TestIqcGate._approve
    _finish = gate_fixture.TestIqcGate._finish

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.supplier = cls.env['res.partner'].create({'name': 'PAR Synthetic Supplier', 'supplier_rank': 1})
        cls.sloc = cls.env.ref('stock.stock_location_suppliers')
        cls.unit = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.product'].create({'name': 'PAR managed component', 'is_storable': True, 'tracking': 'none'})
        opts = {'no_reset_password': True, 'mail_create_nosubscribe': True, 'mail_notrack': True}
        users = cls.env['res.users'].with_context(**opts).env
        cls.stock = new_test_user(users, login='par_stock', groups='stock.group_stock_user',
                                  company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.quality = new_test_user(users, login='par_quality', groups='iatf_incoming_inspection.group_incoming_inspection_user',
                                    company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        # 자기결재 금지: 검사자(quality)와 별도 승인자
        cls.quality_approver = new_test_user(users, login='par_quality_approver',
                                             groups='iatf_incoming_inspection.group_incoming_inspection_user,iatf_document_control.group_document_user',
                                             company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])

    def _qty(self, location, lot=None):
        domain = [('product_id', '=', self.tracked.id), ('location_id', '=', location.id)]
        if lot:
            domain.append(('lot_id', '=', lot.id))
        return sum(self.env['stock.quant'].search(domain).mapped('quantity'))

    def _released_receipt(self):
        self.tracked = self.env['product.product'].create({'name': 'IQC resin (lot)', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({'name': 'PAR-LOT-1', 'product_id': self.tracked.id, 'company_id': self.company.id})
        iqc = self._receipt(quantity=10, product=self.tracked, lot=lot)
        self._approve(iqc, accepted=10)
        self._finish(iqc, 'release')
        self.assertAlmostEqual(self._qty(self.wh.lot_stock_id, lot), 10.0)
        return iqc, lot

    def test_standard_return_of_released_stock_reaches_supplier(self):
        iqc, lot = self._released_receipt()
        receipt = iqc.receipt_move_line_id.picking_id
        wizard = self.env['stock.return.picking'].with_user(self.stock).with_context(
            active_id=receipt.id, active_model='stock.picking').create({})
        wizard.product_return_moves.write({'quantity': 3.0})
        action = wizard.action_create_returns()
        ret = self.env['stock.picking'].browse(action['res_id'])
        self.assertTrue(ret, '표준 반품 전표가 만들어지지 않았다')
        move = ret.move_ids.filtered(lambda m: m.product_id == self.tracked)
        self.assertEqual(len(move), 1)
        self.assertFalse(move.iqc_release_location_id, '반품 이동이 IQC 원천 표시를 물려받았다')
        self.assertFalse(move.iqc_inspection_id)
        self.assertEqual(move.location_dest_id.usage, 'supplier')
        ret.action_assign()
        line = move.move_line_ids[:1] or self.env['stock.move.line'].create({
            'move_id': move.id, 'picking_id': ret.id, 'product_id': self.tracked.id, 'product_uom_id': self.unit.id,
            'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id})
        line.write({'lot_id': lot.id, 'quantity': 3.0})
        move.picked = True
        ret.with_user(self.stock).with_context(skip_backorder=True).button_validate()
        self.assertEqual(ret.state, 'done')
        self.assertAlmostEqual(self._qty(self.wh.lot_stock_id, lot), 7.0, msg='반품 뒤 창고 재고가 3 줄지 않았다')
        self.assertAlmostEqual(self._qty(self.sloc, lot), -7.0, msg='공급사 가상 위치가 입고 −10 + 반품 +3 = −7 이 아니다')
        iqc.invalidate_recordset()
        self.assertAlmostEqual(iqc.quantity_returned, 0.0, msg='합격 후 표준 반품이 검사 문서의 불합격 반품 수량으로 잡혔다')

    def test_pending_stock_and_forged_iqc_moves_still_blocked(self):
        # 검사대기 위치 재고는 여전히 승인된 해제·반품으로만 움직이고, IQC 표시를 단 이동을 손으로 만들 수 없다
        self.tracked = self.env['product.product'].create({'name': 'IQC resin (pending)', 'is_storable': True, 'tracking': 'lot'})
        lot = self.env['stock.lot'].create({'name': 'PAR-LOT-2', 'product_id': self.tracked.id, 'company_id': self.company.id})
        iqc = self._receipt(quantity=5, product=self.tracked, lot=lot)
        pending = iqc.receipt_move_line_id.location_dest_id
        self.assertTrue(pending.iqc_pending)
        with self.assertRaises(UserError):
            self.env['stock.move'].with_user(self.stock).create({
                'name': 'forged', 'product_id': self.tracked.id, 'product_uom': self.unit.id, 'product_uom_qty': 1,
                'location_id': pending.id, 'location_dest_id': self.sloc.id, 'iqc_release_location_id': self.wh.lot_stock_id.id})
        with self.assertRaises(UserError):
            receipt = iqc.receipt_move_line_id.picking_id
            wizard = self.env['stock.return.picking'].with_user(self.stock).with_context(
                active_id=receipt.id, active_model='stock.picking').create({})
            wizard.product_return_moves.write({'quantity': 1.0})
            action = wizard.action_create_returns()
            ret = self.env['stock.picking'].browse(action['res_id'])
            ret.action_assign(); ret.move_ids.picked = True
            ret.with_user(self.stock).with_context(skip_backorder=True).button_validate()

    def test_supplier_destination_alone_does_not_bypass_shipment_gate(self):
        # 위조 방지: 반품이 아닌 출하를 공급사 위치로 보내도 출하검사 게이트는 그대로 선다
        iqc, lot = self._released_receipt()
        picking = self.env['stock.picking'].with_user(self.stock).create({
            'picking_type_id': self.wh.out_type_id.id, 'partner_id': self.supplier.id,
            'location_id': self.wh.lot_stock_id.id, 'location_dest_id': self.sloc.id})
        move = self.env['stock.move'].with_user(self.stock).create({
            'name': 'not a return', 'picking_id': picking.id, 'product_id': self.tracked.id, 'product_uom': self.unit.id,
            'product_uom_qty': 2.0, 'location_id': self.wh.lot_stock_id.id, 'location_dest_id': self.sloc.id})
        picking.action_confirm(); picking.action_assign()
        line = move.move_line_ids[:1] or self.env['stock.move.line'].create({
            'move_id': move.id, 'picking_id': picking.id, 'product_id': self.tracked.id, 'product_uom_id': self.unit.id,
            'location_id': move.location_id.id, 'location_dest_id': move.location_dest_id.id})
        line.write({'lot_id': lot.id, 'quantity': 2.0}); move.picked = True
        self.assertFalse(picking._is_supplier_receipt_return())
        with self.assertRaisesRegex(UserError, '출하검사'):
            picking.with_user(self.stock).with_context(skip_backorder=True).button_validate()
