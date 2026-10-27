import json
from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged, new_test_user
from odoo.tools import file_open


@tagged('post_install', '-at_install')
class TestEvidenceReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()
        cls.env['sq.evidence.binding'].search([('company_id', '=', cls.env.company.id)]).write({'active': False})
        cls.item = cls.env['sq.item'].search([('code', '=', 'INJ.3_1'), ('company_id', '=', cls.env.company.id)], limit=1)

    def rule(self, code, model):
        return self.env['sq.evidence.rule'].search([
            ('item_id.code', '=', code), ('company_id', '=', self.env.company.id), ('model_name', '=', model)], limit=1)

    def bind(self, item, source):
        return self.env['sq.evidence.binding'].create({'item_id': item.id,
            'source_ref': '%s,%s' % (source._name, source.id), 'purpose': '시험 대상 설비의 일상점검 근거'})

    def sheets(self):
        if 'iatf.check.sheet' not in self.env:
            self.skipTest('Optional checklist source not installed')
        return self.env['iatf.check.sheet'].create([
            {'name': 'SQ REVIEW only A', 'company_id': self.env.company.id},
            {'name': 'SQ REVIEW unrelated B', 'company_id': self.env.company.id}])

    def test_checklist_binding_excludes_unrelated_and_draft_but_keeps_ng(self):
        a, b = self.sheets()
        rule = self.rule('INJ.3_1', 'iatf.check.record')
        self.assertTrue(rule._snapshot().get('unavailable'))
        self.bind(self.item, a)
        records = self.env['iatf.check.record']
        for sheet, done in [(a, True), (b, True), (a, False)]:
            record = self.env['iatf.check.record'].create({'sheet_id': sheet.id,
                'company_id': self.env.company.id,
                'line_ids': [(0, 0, {'item_name': '실측 판정', 'result': 'ng'})]})
            if done:
                record.action_done()
            records |= record
        before = records.read(['state', 'overall_result', 'line_ids'])
        target, domain = rule._target()
        self.assertEqual(target.search(domain), records[0])
        self.assertEqual(rule._snapshot()['count'], 1)
        self.assertEqual(records[0].overall_result, 'issue')
        self.assertEqual(records.read(['state', 'overall_result', 'line_ids']), before)
        self.item.binding_ids.active = False
        self.assertTrue(rule._snapshot().get('unavailable'))

    def test_binding_company_and_reader_write_protection(self):
        a, b = self.sheets()
        other = self.env['res.company'].create({'name': 'SQ review foreign company'})
        foreign = self.env['iatf.check.sheet'].create({'name': 'foreign', 'company_id': other.id})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.bind(self.item, foreign)
        viewer = new_test_user(self.env, login='sq.review.viewer', groups='cams_sq.group_sq_user')
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env['sq.evidence.binding'].with_user(viewer).create({
                'item_id': self.item.id, 'source_ref': 'iatf.check.sheet,%s' % a.id, 'purpose': 'unauthorized'})
        # Classification does not grant access to the classified source.
        binding = self.bind(self.item, a)
        outsider = new_test_user(self.env, login='sq.review.nosource', groups='base.group_user,cams_sq.group_sq_user')
        if not self.env['ir.model.access'].with_user(outsider).check('iatf.check.sheet', 'read', False):
            with self.assertRaises(AccessError):
                binding.with_user(outsider).action_open_source()

    def test_documents_must_be_bound_and_approved(self):
        if 'iatf.document' not in self.env:
            self.skipTest('Optional document source not installed')
        category = self.env['iatf.document.category'].create({'name': 'SQ Review', 'code': 'SQ-REVIEW-TEST'})
        approver = new_test_user(self.env, login='sq.review.document.approver',
            groups='iatf_document_control.group_document_manager',
            company_id=self.env.company.id, company_ids=[(6, 0, self.env.company.ids)])
        docs = self.env['iatf.document'].create([
            {'name': name, 'category_id': category.id, 'company_id': self.env.company.id,
             'reviewer_id': approver.id, 'approver_id': approver.id} for name in ('bound approved', 'unrelated approved', 'bound draft')])
        docs[:2].action_submit_review()
        docs[:2].with_user(approver).action_approve()
        rule = self.rule('ASM.1_2', 'iatf.document')
        self.assertTrue(rule._snapshot().get('unavailable'))
        self.bind(rule.item_id, docs[0]); self.bind(rule.item_id, docs[2])
        target, domain = rule._target()
        self.assertEqual(target.search(domain), docs[0])
        self.assertFalse(rule.proposal_enabled)
        self.assertEqual(docs[2].state, 'draft')
        self.assertIn('현재 기준', rule._snapshot()['status'])

    def test_period_uses_business_date_and_current_master_survives_old_creation(self):
        a, b = self.sheets()
        self.bind(self.item, a)
        old = '2026-09-01'
        record = self.env['iatf.check.record'].create({'sheet_id': a.id, 'company_id': self.env.company.id,
            'check_date': old, 'line_ids': [(0, 0, {'item_name': '점검', 'result': 'ok'})]})
        record.action_done()
        self.env.cr.execute('UPDATE iatf_check_sheet SET create_date=%s WHERE id=%s', [old, a.id])
        a.invalidate_recordset(['create_date'])
        ctx = {'sq_date_from': '2026-10-21', 'sq_date_to': '2026-10-21'}
        master = self.rule('INJ.3_1', 'iatf.check.sheet').with_context(**ctx)
        event = self.rule('INJ.3_1', 'iatf.check.record').with_context(**ctx)
        self.assertEqual(master._snapshot()['count'], 1)
        self.assertEqual(event._snapshot()['count'], 0)

    def test_retired_mappings_and_catalog_idempotency(self):
        rules = self.env['sq.evidence.rule'].search([('company_id', '=', self.env.company.id)])
        self.assertFalse(rules.filtered(lambda r: r.item_id.code == 'ASM.1_2' and r.model_name.startswith('injection.')))
        self.assertFalse(rules.filtered(lambda r: r.item_id.code == 'ASM.5_6' and r.model_name == 'iatf.training.record'))
        self.assertTrue(self.rule('ASM.5_6', 'iatf.nonconformity'))
        self.assertTrue(self.rule('ASM.5_6', 'iatf.lot.hold.release'))
        self.assertTrue(self.rule('ASM.5_7', 'iatf.quality.objective'))
        self.assertFalse(rules.filtered(lambda r: r.model_name in ('iatf.jig', 'iatf.reliability.test')))
        ids = self.env['sq.evidence.rule'].with_context(active_test=False).search([]).ids
        self.env['sq.standard'].action_load_catalog()
        self.assertEqual(self.env['sq.evidence.rule'].with_context(active_test=False).search([]).ids, ids)

    def test_migration_preserves_custom_domain_date_metrics_and_disabled_rule(self):
        rule = self.rule('INJ.1_1', 'iatf.control.plan')
        rule.write({'domain_json': '[["id", "=", -1]]', 'review_revision': False,
                    'date_field': 'write_date', 'proposal_enabled': True, 'proposal_source': '담당 검증', 'period_days': 7})
        self.env['sq.standard'].action_load_catalog()
        self.assertEqual(json.loads(rule.domain_json), [['id', '=', -1]])
        self.assertEqual(rule.date_field, 'write_date')
        self.assertTrue(rule.proposal_enabled)
        self.assertEqual(rule.period_days, 7)
        rule.write({'active': False, 'domain_json': '[]'})
        self.env['sq.standard'].action_load_catalog()
        self.assertFalse(rule.active)
        self.assertEqual(rule.date_field, 'write_date')

    def test_active_catalog_fields_exist_and_no_install_dependency_added(self):
        for rule in self.env['sq.evidence.rule'].search([('company_id', '=', self.env.company.id)]):
            if rule.model_name not in self.env:
                continue
            with self.subTest(item=rule.item_id.code, model=rule.model_name):
                self.assertIn(rule.date_field, self.env[rule.model_name]._fields)
                self.assertIn(self.env[rule.model_name]._fields[rule.date_field].type, ('date', 'datetime'))
        self.assertEqual(self.env['ir.module.module'].search([('name', '=', 'cams_sq')]).dependencies_id.mapped('name'), ['iatf_audit'])
