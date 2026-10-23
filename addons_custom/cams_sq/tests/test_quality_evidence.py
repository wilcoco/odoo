from datetime import timedelta
from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestControlledQualityEvidence(TransactionCase):
    def setUp(self):
        super().setUp()
        self.manager = new_test_user(self.env, login='quality_evidence_manager', email='quality-proof@example.invalid',
            groups='iatf_document_control.group_document_manager,iatf_change_management.group_change_management_user')
        self.product = self.env['product.product'].create({'name': 'SYNTHETIC sample product'})
        self.category = self.env['iatf.document.category'].create({'name': 'SYNTHETIC evidence', 'code': 'SYNQE'})

    def document(self, **values):
        vals = dict(name='SYNTHETIC controlled sample', category_id=self.category.id,
            reviewer_id=self.manager.id, approver_id=self.manager.id,
            company_id=self.env.company.id, quality_evidence_kind='limit_sample',
            quality_product_ids=[Command.set(self.product.ids)], physical_reference='SYN-SAMPLE-1',
            storage_location='시험 보관 위치', quality_valid_until=fields.Date.today()+timedelta(days=1))
        vals.update(values)
        return self.env['iatf.document'].create(vals)

    def approve(self, doc):
        doc.action_submit_review()
        doc.with_user(self.manager).action_approve()

    def test_approved_expired_sample_excluded_from_current_evidence(self):
        doc = self.document(quality_valid_until=fields.Date.today()-timedelta(days=1))
        self.approve(doc)
        self.assertFalse(doc.quality_evidence_current)
        self.assertNotIn(doc, self.env['iatf.document'].search([('id', '=', doc.id), ('quality_evidence_current', '=', True)]))
        self.assertIn(doc, self.env['iatf.document'].search([('id', '=', doc.id), ('quality_evidence_current', '=', False)]))

    def test_sample_approval_needs_identity_product_location_and_validity(self):
        doc = self.document(physical_reference=False)
        doc.action_submit_review()
        with self.assertRaises(UserError):
            doc.with_user(self.manager).action_approve()

    def test_revision_preserves_previous_sample_metadata(self):
        doc = self.document()
        self.approve(doc)
        with self.assertRaises(UserError):
            doc.write({'physical_reference': 'replacement'})
        doc.with_user(self.manager).action_new_revision()
        self.assertEqual(doc.revision_ids.sorted('id')[-1].quality_metadata['physical_reference'], 'SYN-SAMPLE-1')
        doc.write({'physical_reference': 'SYN-SAMPLE-2'})
        self.assertFalse(doc.quality_evidence_current)

    def test_invalid_date_and_company_are_rejected(self):
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.document(quality_valid_from=fields.Date.today()+timedelta(days=5))
