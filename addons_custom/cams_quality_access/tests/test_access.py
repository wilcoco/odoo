from odoo import Command
from odoo.tests import TransactionCase, tagged, new_test_user
from odoo.exceptions import AccessError
from ..models.policy import SQ_SOURCES


@tagged('post_install', '-at_install')
class TestQualityReadAccess(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.other = cls.env['res.company'].create({'name': 'SQ access isolation'})
        cls.reader = new_test_user(cls.env, login='sq.source.reader.test',
            groups='base.group_user,cams_quality_access.group_sq_source_reader',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.outsider = new_test_user(cls.env, login='sq.source.outsider.test', groups='base.group_user')

    def test_installed_sources_readable_no_new_mutation(self):
        for name in SQ_SOURCES:
            if name not in self.env:
                continue
            with self.subTest(model=name):
                self.assertTrue(self.env['ir.model.access'].with_user(self.reader).check(name, 'read', False))
                for op in ('write', 'create', 'unlink'):
                    self.assertEqual(
                        self.env['ir.model.access'].with_user(self.reader).check(name, op, False),
                        self.env['ir.model.access'].with_user(self.outsider).check(name, op, False))

    def test_check_record_company_and_mutation(self):
        records = self.env['iatf.check.record']
        for company in (self.company, self.other):
            sheet = self.env['iatf.check.sheet'].create({'name': 'SQ access '+company.name, 'company_id': company.id})
            records |= self.env['iatf.check.record'].create({'sheet_id': sheet.id, 'company_id': company.id})
        own, foreign = records
        self.assertEqual(records.with_user(self.reader).search([('id', 'in', records.ids)]), own)
        own.with_user(self.reader).read(['name', 'line_ids'])
        for record, op in [(foreign, 'read'), (own, 'write'), (own, 'unlink')]:
            with self.assertRaises(AccessError):
                record.with_user(self.reader).check_access(op)

    def test_company_context_cannot_be_forged(self):
        with self.assertRaises(AccessError):
            self.env['iatf.check.record'].with_user(self.reader).with_context(allowed_company_ids=self.other.ids).search([])

    def test_install_idempotence_and_owned_read_only(self):
        domain=[('module','=','cams_quality_access')]
        before=self.env['ir.model.data'].search_count(domain)
        self.env['cams.quality.access.policy']._sync_access()
        self.assertEqual(before,self.env['ir.model.data'].search_count(domain))
        for acl in self.env['ir.model.access'].search([('group_id','in', (self.env.ref('cams_quality_access.group_sq_source_reader')|self.env.ref('cams_quality_access.group_quality_source_reader')).ids)]):
            self.assertTrue(acl.perm_read)
            self.assertFalse(acl.perm_write or acl.perm_create or acl.perm_unlink)
