from datetime import timedelta
from unittest.mock import patch
from odoo import fields
from odoo.exceptions import AccessError,UserError
from .test_iqc_gate import TestIqcGate


class TestCertificate(TestIqcGate):
    def _certificate_receipt(self):
        product=self.env['product.product'].create({'name':'SYNTHETIC certificate resin','is_storable':True,'tracking':'lot',
            'iqc_certificate_required':True,'iqc_shelf_life_required':True,'iqc_shelf_life_days':30})
        lot=self.env['stock.lot'].create({'name':'SYNTHETIC-MILL-LOT','product_id':product.id,'company_id':self.company.id})
        inspection=self._receipt(product=product,lot=lot)
        today=fields.Date.today()
        attachment=self.env['ir.attachment'].with_user(self.quality).create({'name':'SYNTHETIC mill certificate.txt',
            'raw':b'SYNTHETIC MILL LOT CERTIFICATE','res_model':inspection._name,'res_id':inspection.id,'company_id':self.company.id})
        inspection.with_user(self.quality).write({'supplier_cert_no':'SYNTHETIC-CERT','certificate_plant':'SYNTHETIC-PLANT',
            'certificate_lot_name':lot.name,'certificate_issue_date':today,'certificate_manufactured_date':today-timedelta(days=29),
            'certificate_expiry_date':today,'attachment_ids':[(4,attachment.id)]})
        return inspection

    def test_mill_lot_mismatch_blocks_acceptance_and_source_is_frozen(self):
        inspection=self._certificate_receipt()
        inspection.with_user(self.quality).certificate_lot_name='WRONG-LOT'
        with self.assertRaises(UserError),self.cr.savepoint():self._approve(inspection)
        inspection.with_user(self.quality).certificate_lot_name=inspection.lot_id.name
        approved=self._approve(inspection)
        self.assertIn('supplier_certificate',approved.approval_request_id.iqc_scope_snapshot)
        with self.assertRaises(UserError):approved.certificate_plant='CHANGED'
        before=inspection.quantity_pending
        with patch('odoo.addons.iatf_incoming_inspection.models.certificate.fields.Date.context_today',return_value=fields.Date.today()+timedelta(days=1)):
            with self.assertRaises(UserError),self.cr.savepoint():self._finish(inspection)
        self.assertEqual(inspection.quantity_pending,before)
        self._finish(inspection)
        self.assertEqual(inspection.quantity_pending,0)

    def test_unscoped_old_snapshot_and_policy_permissions(self):
        inspection=self._approve(self._receipt())
        self.assertNotIn('supplier_certificate',inspection.approval_request_id.iqc_scope_snapshot)
        with self.assertRaises(AccessError):self.product.with_user(self.stock).write({'iqc_certificate_required':True})
        self.product.iqc_certificate_required=True
        with self.assertRaises(UserError),self.cr.savepoint():self._finish(inspection)
