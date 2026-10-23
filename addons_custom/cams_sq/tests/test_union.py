from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.exceptions import AccessError, UserError
from ..models.union import REVISION


@tagged('post_install', '-at_install')
class TestSqUnion(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()
        groups = 'cams_sq.group_sq_manager,iatf_document_control.group_document_user'
        if cls.env.ref('iatf_work_environment.group_work_environment_user', raise_if_not_found=False):
            groups += ',iatf_work_environment.group_work_environment_user'
        cls.manager = new_test_user(cls.env, login='union.manager', groups=groups)
        cls.reader = new_test_user(cls.env, login='union.reader', groups='cams_sq.group_sq_user')

    def load(self):
        self.env['sq.standard'].with_user(self.manager).action_load_union()
        return self.env['sq.standard'].search([('company_id','=',self.env.company.id),('revision','=',REVISION)])

    def test_union_counts_idempotent_semantic_translation(self):
        old = self.env['sq.item'].search([('standard_id.revision','!=',REVISION)])
        old_data = old.read(['code','points','requirement'])
        standards = self.load()
        self.assertEqual(len(standards), 2)
        self.assertEqual(len(standards.item_ids), 85)
        inj = standards.filtered(lambda s: s.sector == 'INJ')
        self.assertEqual((len(inj.item_ids), inj.total_points, inj.scored_points), (49,1030,1010))
        self.assertEqual(standards.filtered(lambda s: s.sector == 'ASM').total_points,1000)
        domain = [('company_id','=',self.env.company.id)]
        self.assertEqual(self.env['sq.external.finding'].search_count(domain),178)
        self.assertEqual(self.env['sq.standard.value'].search_count(domain),36)
        self.assertEqual(self.env['sq.standard.value'].search_count(domain+[('decision_needed','=',True)]),22)
        self.assertEqual(self.env['sq.item.alias'].search_count([('standard_id','in',standards.ids)]),239)
        counts = {m:self.env[m].search_count([]) for m in ['sq.item','sq.area','sq.item.alias','sq.external.finding','sq.standard.value','sq.evidence.rule','sq.evidence.binding']}
        self.load()
        self.assertEqual(counts,{m:self.env[m].search_count([]) for m in counts})
        self.assertEqual(old.read(['code','points','requirement']),old_data)
        alias = self.env['sq.item.alias'].search([('standard_id','=',inj.id),('revision','=','OURS-48'),('number','=','1_4')])
        self.assertEqual(alias.item_id.code,'INJ.1_5')

    def test_union_normalization_internal_exclusion_unknown(self):
        inj = self.load().filtered(lambda s: s.sector=='INJ')
        audit = self.env['iatf.audit'].create({'title':'UNION TEST SYNTHETIC', 'audit_type':'sq',
            'planned_date':fields.Date.today(),'lead_auditor_id':self.env.uid,'sq_standard_id':inj.id})
        audit.action_sq_initialize()
        self.assertEqual(len(audit.sq_line_ids),49)
        self.assertEqual(audit.sq_applicable,1010)
        audit.sq_line_ids.write({'rating':'good','reason':'Synthetic score test, not plant evidence'})
        self.assertEqual(audit.sq_score,1000)
        internal = audit.sq_line_ids.filtered(lambda l:l.item_id.internal_only)
        internal.write({'rating':'poor'})
        self.assertEqual(audit.sq_score,1000)
        line = (audit.sq_line_ids-internal)[0]
        line.write({'rating':'na','reason':'Synthetic NA'})
        self.assertEqual(audit.sq_applicable,1010-line.points)
        self.assertEqual(audit.sq_score,1000)
        self.assertAlmostEqual(659.5/(1000-60)*1000,701.59574468,places=6)

    def test_no_import_for_reader_and_company_isolation(self):
        standards = self.load()
        with self.assertRaises(UserError):
            self.env['sq.standard'].with_user(self.reader).action_load_union()
        other = self.env['res.company'].create({'name':'Union other company'})
        outsider = new_test_user(self.env,login='union.other',groups='cams_sq.group_sq_manager',company_id=other.id,company_ids=[(6,0,[other.id])])
        finding = self.env['sq.external.finding'].search([('item_id','in',standards.item_ids.ids)],limit=1)
        with self.assertRaises(AccessError):
            finding.with_user(outsider).read(['text'])
        with self.assertRaises(UserError):
            finding.write({'text':'changed'})
