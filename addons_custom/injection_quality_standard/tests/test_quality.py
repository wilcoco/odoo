from odoo.tests import TransactionCase, tagged
from odoo.exceptions import ValidationError, UserError
from odoo.addons.iatf_document_control.models.document import _WORKFLOW_CONTEXT, _WORKFLOW_TOKEN


@tagged('post_install','-at_install')
class TestQualityStandard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product=cls.env['product.product'].search([],limit=1)
        cls.workcenter=cls.env['mrp.workcenter'].search([('company_id','=',cls.env.company.id)],limit=1)
        category=cls.env['iatf.document.category'].search([],limit=1) or cls.env['iatf.document.category'].create({'name':'SQ 시험 문서','code':'SQ-TEST'})
        cls.document=cls.env['iatf.document'].create({'name':'시험 전용 승인 기준','category_id':category.id,'company_id':cls.env.company.id})
        cls.document.with_context(**{_WORKFLOW_CONTEXT:_WORKFLOW_TOKEN}).write({'state':'approved'})
        cls.values={'name':'시험 사출 온도','product_id':cls.product.id,'workcenter_id':cls.workcenter.id,
                    'metric':'oil_temperature','unit':'C','lower':35,'upper':45,'valid_from':'2026-01-01',
                    'document_id':cls.document.id,'reason':'시험용 경계값 검증'}

    def test_bounds_units_and_no_business_mutation(self):
        before=self.env['stock.move'].search_count([])
        limit=self.env['injection.condition.limit'].create(self.values)
        self.assertEqual(limit._classify(35,'C'),'기준 내')
        self.assertEqual(limit._classify(45,'C'),'기준 내')
        self.assertEqual(limit._classify(45.01,'C'),'상·하한 이탈')
        self.assertIn('모름',limit._classify(40,'F'))
        self.assertEqual(before,self.env['stock.move'].search_count([]))

    def test_overlapping_criteria_rejected(self):
        self.env['injection.condition.limit'].create(self.values)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['injection.condition.limit'].create(dict(self.values,name='겹침'))

    def test_invalid_limits_rejected(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['injection.condition.limit'].create(dict(self.values,lower=50))

    def test_unapproved_basis_rejected(self):
        self.document.with_context(**{_WORKFLOW_CONTEXT:_WORKFLOW_TOKEN}).write({'state':'draft'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['injection.condition.limit'].create(self.values)

    def test_startup_positive_quantity(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['injection.startup.standard'].create({'name':'시험','product_id':self.product.id,
                'trigger':'startup','quantity':0,'document_id':self.document.id,'reason':'시험'})

    def test_scrap_snapshot_cannot_be_forged(self):
        with self.assertRaises(UserError):
            self.env['stock.scrap'].create({'product_id':self.product.id,'startup_basis':{'fake':True}})
