import base64

from odoo import Command
from odoo.tests.common import TransactionCase, tagged, new_test_user
from odoo.exceptions import UserError, AccessError


@tagged('post_install','-at_install')
class TestIqcGate(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company=cls.env.company
        cls.wh=cls.env['stock.warehouse'].search([('company_id','=',cls.company.id)],limit=1)
        cls.supplier=cls.env['res.partner'].create({'name':'IQC Synthetic Supplier','supplier_rank':1})
        cls.sloc=cls.env.ref('stock.stock_location_suppliers')
        cls.production=cls.env['stock.location'].create({'name':'IQC synthetic production','usage':'production','company_id':cls.company.id})
        cls.unit=cls.env.ref('uom.product_uom_unit')
        cls.product=cls.env['product.product'].create({'name':'IQC managed component','is_storable':True,'tracking':'none'})
        opts={'no_reset_password':True,'mail_create_nosubscribe':True,'mail_notrack':True}
        cls.stock=new_test_user(cls.env['res.users'].with_context(**opts).env,login='iqc_stock',groups='stock.group_stock_user',company_id=cls.company.id,company_ids=[Command.set(cls.company.ids)])
        cls.quality=new_test_user(cls.env['res.users'].with_context(**opts).env,login='iqc_quality',groups='iatf_incoming_inspection.group_incoming_inspection_user',company_id=cls.company.id,company_ids=[Command.set(cls.company.ids)])

    def _receipt(self,quantity=10,product=None,lot=None,owner=None,package=None,uom=None,purchase_line=None):
        product=product or self.product
        uom=uom or self.unit
        picking=self.env['stock.picking'].with_user(self.stock).create({'picking_type_id':self.wh.in_type_id.id,
            'partner_id':self.supplier.id,'location_id':self.sloc.id,'location_dest_id':self.wh.lot_stock_id.id})
        vals={'name':'IQC receipt','picking_id':picking.id,'product_id':product.id,'product_uom':uom.id,
            'product_uom_qty':quantity,'location_id':self.sloc.id,'location_dest_id':self.wh.lot_stock_id.id}
        if purchase_line:
            vals['purchase_line_id']=purchase_line.id
        move=self.env['stock.move'].with_user(self.stock).create(vals)
        move._action_confirm()
        move.move_line_ids.unlink()
        line=self.env['stock.move.line'].with_user(self.stock).create({'move_id':move.id,'picking_id':picking.id,
            'product_id':product.id,'product_uom_id':uom.id,'quantity':quantity,
            'location_id':self.sloc.id,'location_dest_id':self.wh.lot_stock_id.id,
            'lot_id':lot.id if lot else False,'owner_id':owner.id if owner else False,
            'result_package_id':package.id if package else False})
        move.picked=True
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state,'done')
        iqc=self.env['iatf.incoming.inspection'].search([('receipt_move_line_id','=',line.id)])
        self.assertEqual(len(iqc),1)
        return iqc

    def _approve(self,iqc,accepted=10,rejected=0):
        rec=iqc.with_user(self.quality)
        rec.action_start_inspection()
        rec.write({'inspection_type':'full','quantity_inspected':accepted+rejected,
            'quantity_accepted':accepted,'quantity_rejected':rejected,
            'result':'pass' if accepted==rec.quantity_received else ('partial' if accepted else 'fail'),
            'disposition':'accept' if accepted else 'return','line_ids':[Command.create({
                'characteristic_name':'외관','specification':'균열 없음','measured_value':'수량별 외관 확인',
                'result':'pass' if not rejected else 'fail'})]})
        rec.action_decide()
        rec.approval_request_id.write({'line_ids':[Command.create({'sequence':10,'user_id':self.quality.id})]})
        rec.action_submit_approval()
        rec.action_approve_approval()
        self.assertEqual(rec.approval_state,'approved')
        return rec

    def _finish(self,iqc,kind='release'):
        action=getattr(iqc.with_user(self.stock),'action_prepare_'+kind)()
        picking=self.env['stock.picking'].browse(action['res_id']).with_user(self.stock)
        picking.move_ids.picked=True
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state,'done')
        return picking

    def _consume(self,qty,product=None,lot=None):
        product=product or self.product
        move=self.env['stock.move'].create({'name':'Production consume','product_id':product.id,
            'product_uom':self.unit.id,'product_uom_qty':qty,'location_id':self.wh.lot_stock_id.id,
            'location_dest_id':self.production.id})
        move._action_confirm()
        self.env['stock.move.line'].create({'move_id':move.id,'product_id':product.id,'product_uom_id':self.unit.id,
            'quantity':qty,'lot_id':lot.id if lot else False,'location_id':move.location_id.id,'location_dest_id':move.location_dest_id.id})
        move.picked=True
        return move._action_done()

    def test_lotless_pending_cannot_be_consumed(self):
        iqc=self._receipt()
        self.assertEqual(iqc.quantity_inspected,0)
        self.assertFalse(iqc.lot_id)
        self.assertEqual(iqc.receipt_move_line_id.location_dest_id,iqc.picking_id.iqc_pending_location_id)
        self.assertNotIn(iqc.picking_id.iqc_pending_location_id,self.env['stock.location'].search([('id','child_of',self.wh.lot_stock_id.id)]))
        with self.assertRaises(UserError),self.env.cr.savepoint():
            self._consume(10)
        self.assertEqual(iqc.quantity_pending,10)

    def test_normal_stock_quality_release(self):
        iqc=self._approve(self._receipt())
        before=iqc.receipt_move_line_id.location_dest_id
        self.assertEqual(self.env['stock.quant']._get_available_quantity(self.product,self.wh.lot_stock_id),0)
        release=self._finish(iqc)
        self.assertFalse(release.move_ids.purchase_line_id)
        self.assertFalse(release.move_ids.origin_returned_move_id)
        self.assertEqual(release.move_ids.location_id,before)
        self.assertEqual(self.env['stock.quant']._get_available_quantity(self.product,self.wh.lot_stock_id),10)
        self._consume(10)
        iqc.action_close()
        self.assertEqual(iqc.state,'closed')

    def test_changed_attachment_cannot_release_approved_receipt(self):
        iqc = self._receipt()
        attachment = self.env['ir.attachment'].create({
            'name': 'SYNTHETIC receipt measurements.txt',
            'datas': base64.b64encode(b'ORIGINAL RECEIPT OBSERVATIONS'),
            'res_model': iqc._name, 'res_id': iqc.id})
        iqc.write({'attachment_ids': [Command.link(attachment.id)]})
        self._approve(iqc)
        attachment.write({'datas': base64.b64encode(b'REPLACED AFTER SIGNATURE')})
        with self.assertRaises(UserError):
            self._finish(iqc)
        self.assertEqual(iqc.quantity_released, 0)

    def test_changed_document_cannot_release_approved_receipt(self):
        iqc = self._receipt()
        category = self.env['iatf.document.category'].create({'name': 'SYNTHETIC inspection source', 'code': 'SYN-IQC-SOURCE'})
        document = self.env['iatf.document'].create({'name': 'SYNTHETIC linked observations',
            'category_id': category.id, 'description': '<p>Original observations</p>',
            'company_id': self.company.id})
        iqc.write({'document_ids': [Command.link(document.id)]})
        self._approve(iqc)
        document.write({'description': '<p>Changed observations after inspection approval</p>'})
        with self.assertRaises(UserError):
            self._finish(iqc)
        self.assertEqual(iqc.quantity_released, 0)

    def test_unchanged_source_file_releases_without_document_edit_rights(self):
        iqc = self._receipt()
        attachment = self.env['ir.attachment'].create({'name': 'SYNTHETIC receipt source.txt',
            'datas': base64.b64encode(b'UNCHANGED APPROVED OBSERVATIONS'),
            'res_model': iqc._name, 'res_id': iqc.id})
        iqc.write({'attachment_ids': [Command.link(attachment.id)]})
        self._approve(iqc)
        self._finish(iqc)
        self.assertEqual(iqc.quantity_released, 10)
        snapshot = iqc.approval_request_id.iqc_scope_snapshot['linked_evidence']
        self.assertEqual(snapshot['attachments'][0]['checksum'], attachment.checksum)

    def test_foreign_or_unreadable_document_link_is_rolled_back(self):
        iqc = self._receipt()
        category = self.env['iatf.document.category'].create({'name': 'SYNTHETIC access', 'code': 'SYN-IQC-ACCESS'})
        doc = self.env['iatf.document'].create({'name': 'SYNTHETIC controlled source',
            'category_id': category.id, 'company_id': self.company.id})
        with self.assertRaises(AccessError):
            iqc.with_user(self.quality).write({'document_ids': [Command.link(doc.id)]})
        self.assertFalse(iqc.document_ids)
        foreign_company = self.env['res.company'].create({'name': 'SYNTHETIC source other company'})
        doc.write({'company_id': foreign_company.id})
        with self.assertRaises(UserError):
            iqc.write({'document_ids': [Command.link(doc.id)]})
        self.assertFalse(iqc.document_ids)

    def test_partial_release_return_po_quantities(self):
        po=self.env['purchase.order'].create({'partner_id':self.supplier.id,'order_line':[Command.create({
            'product_id':self.product.id,'name':self.product.name,'product_qty':10,'product_uom':self.unit.id,'price_unit':100})]})
        po.button_confirm()
        # Use the actual PO receipt generated by standard purchase_stock.
        picking=po.picking_ids
        picking.move_ids.quantity=10
        picking.move_ids.picked=True
        picking.with_user(self.stock).with_context(skip_backorder=True).button_validate()
        iqc=picking.iqc_inspection_ids
        self._approve(iqc,6,4)
        self.assertEqual(po.order_line.qty_received,10)
        self._finish(iqc)
        self.assertEqual(po.order_line.qty_received,10)
        returned=self._finish(iqc,'return')
        self.assertEqual(returned.move_ids.origin_returned_move_id,picking.move_ids)
        self.assertEqual(po.order_line.qty_received,6)
        self.assertFalse(po.invoice_ids)
        iqc.with_user(self.quality).action_close()
        self.assertTrue(iqc.nonconformity_id)

    def test_same_lot_receipts_are_independent(self):
        product=self.env['product.product'].create({'name':'IQC lot component','tracking':'lot','is_storable':True})
        lot=self.env['stock.lot'].create({'name':'IQC-SAME-LOT','product_id':product.id,'company_id':self.company.id})
        first=self._receipt(product=product,lot=lot)
        second=self._receipt(product=product,lot=lot)
        self.assertNotEqual(first.receipt_move_line_id.location_dest_id,second.receipt_move_line_id.location_dest_id)
        self._approve(first)
        self._finish(first)
        self.assertEqual(second.quantity_pending,10)
        self.assertEqual(second.state,'draft')
        self.assertFalse(lot.quality_hold)
        self._consume(10,product,lot)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            self._consume(1,product,lot)

    def test_approval_and_source_forgery(self):
        iqc=self._receipt()
        for vals in [{'state':'decided'},{'quantity_received':100},{'approved_by':self.stock.id},
                     {'receipt_snapshot':{}},{'receipt_move_line_id':False}]:
            with self.assertRaises(UserError),self.env.cr.savepoint():
                iqc.with_user(self.quality).write(vals)
        iqc.with_user(self.quality).action_start_inspection()
        iqc.with_user(self.quality).write({'result':'pass','quantity_accepted':10})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.with_user(self.quality).action_decide()
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.with_user(self.stock).action_prepare_release()
        with self.assertRaises(AccessError),self.env.cr.savepoint():
            iqc.with_user(self.stock).write({'result':'pass'})

    def test_pending_quant_and_move_bypass(self):
        iqc=self._receipt()
        pending=iqc.receipt_move_line_id.location_dest_id
        quant=self.env['stock.quant'].search([('location_id','=',pending.id)])
        for vals in [{'quantity':0},{'reserved_quantity':0},{'location_id':self.wh.lot_stock_id.id},{'inventory_quantity':0}]:
            with self.assertRaises(UserError),self.env.cr.savepoint():
                quant.write(vals)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            quant.unlink()
        move=self.env['stock.move'].create({'name':'Bypass','product_id':self.product.id,'product_uom':self.unit.id,
            'product_uom_qty':10,'location_id':pending.id,'location_dest_id':self.wh.lot_stock_id.id})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move._action_confirm()._action_assign()
        with self.assertRaises(UserError),self.env.cr.savepoint():
            self.env['stock.quant'].with_context(default_location_id=pending.id).create({'product_id':self.product.id,'quantity':10})

    def test_pending_api_and_legacy_stock(self):
        self.env['stock.quant']._update_available_quantity(self.product,self.wh.lot_stock_id,3)
        iqc=self._receipt()
        rows=self.env['stock.quant']._iqc_pending_quantities(self.company.id,[self.product.id],self.wh.id)
        self.assertEqual(sum(r['quantity'] for r in rows),10)
        self._consume(3)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            self._consume(1)
        self.assertEqual(iqc.quantity_pending,10)

    def test_duplicate_prepare_and_closed_evidence(self):
        iqc=self._approve(self._receipt())
        self._finish(iqc)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.with_user(self.stock).action_prepare_release()
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.with_user(self.quality).line_ids.write({'result':'fail'})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.receipt_move_line_id.write({'quantity':1})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.movement_ids.write({'state':'cancel'})
        old=iqc.approval_request_id
        iqc.with_user(self.quality).action_reset_inspection()
        self.assertNotEqual(old,iqc.approval_request_id)
        self.assertEqual(old.state,'approved')
        self.assertEqual(old.iqc_scope_snapshot['quantity_accepted'],10)

    def test_approved_owner_package_and_uom(self):
        dozen=self.env.ref('uom.product_uom_dozen')
        owner=self.env['res.partner'].create({'name':'Synthetic consignment owner'})
        package=self.env['stock.quant.package'].create({'name':'IQC synthetic package'})
        iqc=self._receipt(2,owner=owner,package=package,uom=dozen)
        self._approve(iqc,2,0)
        release=self._finish(iqc)
        self.assertEqual(release.move_line_ids.owner_id,owner)
        self.assertEqual(release.move_line_ids.package_id,package)
        self.assertEqual(release.move_line_ids.product_uom_id,dozen)
        self.assertEqual(self.env['stock.quant'].search([('product_id','=',self.product.id),
            ('location_id','=',self.wh.lot_stock_id.id),('owner_id','=',owner.id)]).quantity,24)

    def test_receipt_detail_create_and_defaults_blocked(self):
        iqc=self._receipt()
        move=iqc.receipt_move_line_id.move_id
        for payload,context in [({'move_id':move.id},{}),({}, {'default_move_id':move.id})]:
            with self.assertRaises(UserError),self.env.cr.savepoint():
                self.env['stock.move.line'].with_user(self.stock).with_context(**context).create(dict(payload,
                    product_id=self.product.id,product_uom_id=self.unit.id,quantity=100,
                    location_id=self.sloc.id,location_dest_id=self.wh.lot_stock_id.id))
        with self.assertRaises(UserError),self.env.cr.savepoint():
            self.env['iatf.incoming.inspection'].with_user(self.quality).with_context(default_receipt_move_line_id=move.move_line_ids.id).create({
                'supplier_id':self.supplier.id,'product_id':self.product.id,'quantity_received':10,'quantity_inspected':10})

    def test_partial_release_backorder_exact_coverage(self):
        iqc=self._approve(self._receipt())
        action=iqc.with_user(self.stock).action_prepare_release()
        picking=self.env['stock.picking'].browse(action['res_id']).with_user(self.stock)
        picking.move_line_ids.quantity=6
        picking.move_ids.picked=True
        picking.move_ids._action_done()
        self.assertEqual(iqc.quantity_released,6)
        backorder=iqc.movement_ids.filtered(lambda m:m.state not in ('done','cancel'))
        self.assertEqual(len(backorder),1)
        self.assertEqual(backorder.product_uom_qty,4)
        backorder.with_user(self.stock)._action_assign()
        backorder.with_user(self.stock).picked=True
        backorder.with_user(self.stock)._action_done()
        self.assertEqual(iqc.quantity_released,10)
        self.assertEqual(iqc.quantity_pending,0)

    def test_other_job_reservation_is_not_consumed(self):
        iqc=self._approve(self._receipt())
        self._finish(iqc)
        other=self.env['stock.move'].create({'name':'Other job','product_id':self.product.id,'product_uom':self.unit.id,
            'product_uom_qty':7,'location_id':self.wh.lot_stock_id.id,'location_dest_id':self.production.id})
        other._action_confirm()._action_assign()
        self.assertEqual(other.quantity,7)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            self._consume(4)
        self._consume(3)
        self.assertEqual(other.quantity,7)

    def test_iqc_cross_company_read_and_action_blocked(self):
        iqc=self._receipt()
        company=self.env['res.company'].create({'name':'Other IQC company'})
        other=new_test_user(self.env['res.users'].with_context(no_reset_password=True).env,
            login='iqc_other',groups='stock.group_stock_user,iatf_incoming_inspection.group_incoming_inspection_user',
            company_id=company.id,company_ids=[Command.set(company.ids)])
        self.assertFalse(self.env['iatf.incoming.inspection'].with_user(other).search([('id','=',iqc.id)]))
        with self.assertRaises(AccessError),self.env.cr.savepoint():
            iqc.with_user(other).action_start_inspection()
        with self.assertRaises(AccessError),self.env.cr.savepoint():
            self.env['stock.quant'].with_user(other)._iqc_pending_quantities(self.company.id)

    def test_pending_destination_cannot_receive_inventory_adjustment(self):
        iqc=self._receipt()
        inventory=self.env['stock.location'].create({'name':'Synthetic inventory adjustment','usage':'inventory','company_id':self.company.id})
        pending=iqc.receipt_move_line_id.location_dest_id
        move=self.env['stock.move'].create({'name':'Fake inventory','product_id':self.product.id,'product_uom':self.unit.id,
            'product_uom_qty':100,'location_id':inventory.id,'location_dest_id':pending.id})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move._action_confirm()._action_assign()
        self.assertEqual(iqc.quantity_pending,10)

    def test_independent_lot_hold_is_never_cleared(self):
        product=self.env['product.product'].create({'name':'Held purchased component','is_storable':True,'tracking':'lot'})
        lot=self.env['stock.lot'].create({'name':'INDEPENDENT-HOLD','product_id':product.id,'company_id':self.company.id,
            'quality_hold':True,'hold_reason':'Independent safety recall'})
        iqc=self._receipt(product=product,lot=lot)
        self._approve(iqc)
        self.assertTrue(lot.quality_hold)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.with_user(self.stock).action_prepare_release()
        self.assertEqual(lot.hold_reason,'Independent safety recall')

    def test_conditional_and_skip_do_not_release(self):
        iqc=self._receipt().with_user(self.quality)
        iqc.action_start_inspection()
        iqc.write({'inspection_type':'skip','quantity_inspected':10,'quantity_accepted':10,'result':'conditional',
            'disposition':'concession','line_ids':[Command.create({'characteristic_name':'외관','specification':'양호',
                'measured_value':'확인','result':'pass'})]})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.action_decide()
        self.assertEqual(iqc.quantity_pending,10)

    def test_receipt_backorder_preserves_original_destination(self):
        po=self.env['purchase.order'].create({'partner_id':self.supplier.id,'order_line':[Command.create({
            'product_id':self.product.id,'name':self.product.name,'product_qty':10,'product_uom':self.unit.id,'price_unit':100})]})
        po.button_confirm()
        picking=po.picking_ids.with_user(self.stock)
        picking.move_ids.quantity=6
        picking.move_ids.picked=True
        picking.move_ids._action_done()
        first=picking.iqc_inspection_ids
        self.assertEqual(first.quantity_received,6)
        remaining=po.picking_ids.filtered(lambda p:p.state not in ('done','cancel'))
        self.assertEqual(len(remaining),1)
        remaining.move_ids.quantity=4
        remaining.move_ids.picked=True
        remaining.with_user(self.stock).with_context(skip_backorder=True).button_validate()
        second=remaining.iqc_inspection_ids
        self.assertEqual(second.quantity_received,4)
        self.assertEqual(second.receipt_move_line_id.iqc_release_location_id,self.wh.lot_stock_id)
        self.assertNotEqual(first.receipt_move_line_id.location_dest_id,second.receipt_move_line_id.location_dest_id)
        self._approve(second,4)
        self._finish(second)
        self.assertEqual(first.quantity_pending,6)
        self.assertEqual(po.order_line.qty_received,10)

    def test_same_receipt_multiple_lots_generate_exact_scopes(self):
        product=self.env['product.product'].create({'name':'Multi lot component','is_storable':True,'tracking':'lot'})
        lots=self.env['stock.lot'].create([{'name':'IQC-MULTI-A','product_id':product.id,'company_id':self.company.id},
            {'name':'IQC-MULTI-B','product_id':product.id,'company_id':self.company.id}])
        picking=self.env['stock.picking'].create({'picking_type_id':self.wh.in_type_id.id,'partner_id':self.supplier.id,
            'location_id':self.sloc.id,'location_dest_id':self.wh.lot_stock_id.id})
        move=self.env['stock.move'].create({'name':'Two lots','picking_id':picking.id,'product_id':product.id,
            'product_uom':self.unit.id,'product_uom_qty':10,'location_id':self.sloc.id,'location_dest_id':self.wh.lot_stock_id.id})
        move._action_confirm()
        move.move_line_ids.unlink()
        for lot,quantity in zip(lots,[3,7]):
            self.env['stock.move.line'].create({'move_id':move.id,'product_id':product.id,'product_uom_id':self.unit.id,
                'lot_id':lot.id,'quantity':quantity,'location_id':self.sloc.id,'location_dest_id':self.wh.lot_stock_id.id})
        move.picked=True
        picking.with_user(self.stock).with_context(skip_backorder=True).button_validate()
        inspections=picking.iqc_inspection_ids
        self.assertEqual(len(inspections),2)
        chosen=inspections.filtered(lambda i:i.lot_id==lots[1])
        self._approve(chosen,7)
        released=self._finish(chosen)
        self.assertEqual(released.move_line_ids.lot_id,lots[1])
        self.assertEqual((inspections-chosen).quantity_pending,3)
        picking.with_user(self.stock)._create_iqc_inspections()
        self.assertEqual(len(picking.iqc_inspection_ids),2)

    def test_two_step_receipt_releases_to_input_then_stock(self):
        warehouse=self.env['stock.warehouse'].create({'name':'IQC two step warehouse','code':'IQ2','company_id':self.company.id,'reception_steps':'two_steps'})
        po=self.env['purchase.order'].create({'partner_id':self.supplier.id,'picking_type_id':warehouse.in_type_id.id,
            'order_line':[Command.create({'product_id':self.product.id,'name':self.product.name,
                'product_qty':10,'product_uom':self.unit.id,'price_unit':100})]})
        po.button_confirm()
        receipt=po.picking_ids.filtered(lambda p:p.picking_type_code=='incoming')
        receipt.move_ids.quantity=10
        receipt.move_ids.picked=True
        receipt.with_user(self.stock).with_context(skip_backorder=True).button_validate()
        iqc=receipt.iqc_inspection_ids
        self.assertEqual(iqc.receipt_move_line_id.iqc_release_location_id,warehouse.wh_input_stock_loc_id)
        self._approve(iqc)
        release=self._finish(iqc)
        self.assertEqual(release.move_ids.location_dest_id,warehouse.wh_input_stock_loc_id)
        transfer=self.env['stock.move'].search([('product_id','=',self.product.id),
            ('location_id','=',warehouse.wh_input_stock_loc_id.id),('location_dest_id','=',warehouse.lot_stock_id.id),
            ('state','not in',('done','cancel'))])
        self.assertEqual(len(transfer),1)
        transfer.with_user(self.stock)._action_assign()
        transfer.with_user(self.stock).picked=True
        transfer.with_user(self.stock)._action_done()
        self.assertEqual(self.env['stock.quant']._get_available_quantity(self.product,warehouse.lot_stock_id),10)
        self.assertEqual(po.order_line.qty_received,10)

    def test_forged_movement_scope_and_done_state(self):
        iqc=self._approve(self._receipt())
        action=iqc.with_user(self.stock).action_prepare_release()
        move=self.env['stock.picking'].browse(action['res_id']).move_ids.with_user(self.stock)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move.write({'state':'done'})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move.move_line_ids.write({'quantity':11})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move.move_line_ids.write({'location_dest_id':self.sloc.id})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move.write({'iqc_approval_request_id':False})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move.write({'product_uom_qty':-100})
        with self.assertRaises(UserError),self.env.cr.savepoint():
            move.write({'product_uom_qty':100})
        self.assertEqual(iqc.quantity_released,0)
        self.assertEqual(iqc.quantity_pending,10)

    def test_cancel_pending_release_then_reapprove_without_history_loss(self):
        iqc=self._approve(self._receipt())
        action=iqc.with_user(self.stock).action_prepare_release()
        pending=self.env['stock.picking'].browse(action['res_id']).with_user(self.stock)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            iqc.action_reset_inspection()
        pending.action_cancel()
        old=iqc.approval_request_id
        iqc.action_reset_inspection()
        iqc.write({'quantity_accepted':6,'quantity_rejected':4,'result':'partial'})
        iqc.line_ids.write({'result':'fail','measured_value':'4 parts rejected on reinspection'})
        iqc.action_decide()
        iqc.action_submit_approval()
        iqc.action_approve_approval()
        self._finish(iqc)
        self.assertEqual(iqc.quantity_released,6)
        self.assertEqual(iqc.quantity_pending,4)
        self.assertEqual(old.iqc_scope_snapshot['quantity_accepted'],10)
        self.assertEqual(old.state,'approved')

    def test_partial_reinspection_preserves_ncr_and_cumulative_movement(self):
        iqc=self._approve(self._receipt(),4,2)
        self._finish(iqc)
        self._finish(iqc,'return')
        previous=iqc.approval_request_id
        previous_nc=iqc.nonconformity_id
        iqc.action_reset_inspection()
        iqc.write({'quantity_inspected':10,'quantity_accepted':6,'quantity_rejected':4,'result':'partial'})
        iqc.line_ids.write({'measured_value':'Additional two failed; total four rejected'})
        iqc.action_decide()
        iqc.action_submit_approval()
        iqc.action_approve_approval()
        self._finish(iqc)
        self._finish(iqc,'return')
        iqc.action_close()
        self.assertEqual(iqc.quantity_released,6)
        self.assertEqual(iqc.quantity_returned,4)
        self.assertEqual(previous.iqc_scope_snapshot['quantity_rejected'],2)
        self.assertNotEqual(iqc.nonconformity_id,previous_nc)
        self.assertEqual(previous_nc.sudo().quantity_rejected,2)
        self.assertEqual(iqc.nonconformity_id.sudo().quantity_rejected,4)
        self.assertEqual(len(iqc.nonconformity_history_ids),2)

    def test_quality_can_read_receipt_evidence_without_stock_write(self):
        iqc=self._approve(self._receipt(),6,4)
        result=iqc.read(['name','picking_id','receipt_move_line_id','product_id','lot_id','supplier_id',
                         'nonconformity_summary','quantity_pending','quantity_released'])
        self.assertTrue(result[0]['nonconformity_summary'])
        self.assertFalse(self.env['stock.move'].with_user(self.quality).has_access('write'))
        action=iqc.action_create_nc()
        self.assertEqual(action['res_model'],'iatf.incoming.inspection')

    def test_supplier_backorder_split_needs_no_iqc_capability(self):
        """Same ordinary ORM boundary used by ASN: create(move._split(2))."""
        self._supplier_backorder_split()

    def test_legacy_supplier_backorder_metadata_is_not_copied(self):
        """An already-existing remainder may still carry the old copied marker."""
        self._supplier_backorder_split(legacy_metadata=True)

    def _supplier_backorder_split(self, legacy_metadata=False):
        from odoo.addons.iatf_incoming_inspection.models.iqc_service import service
        po=self.env['purchase.order'].create({'partner_id':self.supplier.id,'order_line':[Command.create({
            'product_id':self.product.id,'name':self.product.name,'product_qty':10,
            'product_uom':self.unit.id,'price_unit':100})]})
        po.button_confirm()
        receipt=po.picking_ids.with_user(self.stock)
        receipt.move_ids.quantity=6
        receipt.move_ids.picked=True
        receipt.move_ids._action_done()
        first=receipt.iqc_inspection_ids
        remaining=po.picking_ids.filtered(lambda p:p.state not in ('done','cancel')).move_ids.with_user(self.stock)
        self.assertEqual((po.order_line.qty_received,remaining.product_qty),(6,4))
        if legacy_metadata:
            # Reproduce the pre-fix persisted remainder only in this synthetic fixture.
            service(remaining).write({'iqc_release_location_id':self.wh.lot_stock_id.id})
        remaining._do_unreserve()
        payload=remaining._split(2)
        child=self.env['stock.move'].with_user(self.stock).create(payload)
        self.assertFalse(child.iqc_release_location_id)
        self.assertEqual(child.location_dest_id,self.wh.lot_stock_id)
        self.assertEqual(child.purchase_line_id,po.order_line)
        self.assertEqual((child.product_qty,remaining.product_qty),(2,2))
        child._action_confirm(merge=False)
        child.quantity=2
        child.picked=True
        child._action_done()
        added=self.env['iatf.incoming.inspection'].search([('receipt_move_line_id','in',child.move_line_ids.ids)])
        self.assertEqual(added.quantity_received,2)
        self.assertEqual(added.receipt_move_line_id.iqc_release_location_id,self.wh.lot_stock_id)
        self.assertEqual(first.quantity_pending,6)
        self.assertEqual(po.order_line.qty_received,8)
        self.assertEqual(remaining.product_qty,2)
        with self.assertRaises(UserError),self.env.cr.savepoint():
            self.env['stock.move'].with_user(self.stock).with_context(
                default_iqc_release_location_id=self.wh.lot_stock_id.id).create({
                    'name':'Forbidden IQC marker','product_id':self.product.id,
                    'product_uom':self.unit.id,'product_uom_qty':1,
                    'location_id':self.sloc.id,'location_dest_id':self.wh.lot_stock_id.id})
