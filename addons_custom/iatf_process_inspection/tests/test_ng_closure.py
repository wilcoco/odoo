from odoo import Command
from odoo.exceptions import AccessError,UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestNgClosure(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.quality=new_test_user(cls.env,login='p1-ng-inspector',groups='iatf_process_inspection.group_process_inspection_user,iatf_nonconformity.group_nc_user')
        cls.manager=new_test_user(cls.env,login='p1-ng-manager',groups='iatf_process_inspection.group_process_inspection_manager,iatf_nonconformity.group_nc_manager')
        cls.product=cls.env['product.product'].create({'name':'SYNTHETIC NG closure part','is_storable':True,'tracking':'lot'})
        cls.lot=cls.env['stock.lot'].create({'name':'SYNTHETIC NG closure lot','product_id':cls.product.id,'company_id':cls.env.company.id})
    def _inspection(self):
        return self.env['iatf.process.inspection'].with_user(self.quality).create({'product_id':self.product.id,
            'lot_id':self.lot.id,'inspection_stage':'ipqc','quantity_produced':1,'quantity_inspected':1,
            'quantity_accepted':0,'quantity_rejected':1,'result':'fail',
            'line_ids':[Command.create({'characteristic_name':'SYNTHETIC visual','specification':'No crack',
                'measured_value':'Crack observed','result':'fail'})]})
    def test_ng_closure_requires_verified_approved_disposition_and_preserves_stock(self):
        record=self._inspection();record.action_decide()
        self.assertTrue(self.lot.quality_hold)
        with self.assertRaises(AccessError):record.action_close()
        record=record.with_user(self.manager)
        with self.assertRaises(UserError):record.action_close()
        record.ng_closure_note='SYNTHETIC source remains on hold; defect correction verified'
        nc=record.nonconformity_id.with_user(self.quality)
        nc.write({'verification_result':'SYNTHETIC corrective action effective',
            'corrective_action_ids':[Command.create({'description':'SYNTHETIC correct cause','effective':'yes',
                'verification_result':'SYNTHETIC verification completed'})]})
        nc.corrective_action_ids.action_start();nc.corrective_action_ids.action_implement();nc.corrective_action_ids.action_verify()
        nc.action_close()
        with self.assertRaises(UserError):record.action_close()
        nc.approval_line_ids=[Command.create({'user_id':self.manager.id})]
        nc.action_submit_approval();nc.with_user(self.manager).action_approve_approval()
        quants=self.env['stock.quant'].search([('lot_id','=',self.lot.id)])
        before=quants.read(['quantity','reserved_quantity'])
        record.action_close()
        self.assertEqual(record.state,'closed')
        self.assertTrue(record.ng_closure_snapshot['lot_hold'])
        self.assertTrue(self.lot.quality_hold)
        self.assertEqual(quants.read(['quantity','reserved_quantity']),before)
        with self.assertRaises(UserError):record.ng_closure_snapshot={}
        with self.assertRaises(UserError):record.ng_closure_note='rewritten'
    def test_rpc_cannot_create_or_assign_ng_closed(self):
        record=self._inspection()
        with self.assertRaises(UserError):record.with_user(self.manager).write({'state':'closed'})
        with self.assertRaises(UserError),self.cr.savepoint():record.copy({'state':'closed'})
        with self.assertRaises(UserError):record.with_context(_ng_close_token=True).write({'ng_closed_by_id':self.manager.id})
