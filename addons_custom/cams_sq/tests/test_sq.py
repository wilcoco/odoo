import json
import base64
import io
import zipfile
from freezegun import freeze_time
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tests import tagged
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo import fields


@tagged('post_install', '-at_install')
class TestSq(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()
        cls.standard = cls.env['sq.standard'].search([('sector', '=', 'INJ'), ('company_id', '=', cls.env.company.id)], limit=1)

    def assessment(self):
        audit = self.env['iatf.audit'].create({'title': 'SQ 시험 평가', 'audit_type': 'sq',
            'planned_date': fields.Date.today(), 'lead_auditor_id': self.env.uid,
            'company_id': self.env.company.id, 'sq_standard_id': self.standard.id,
            'sq_date_from': '2026-10-21', 'sq_date_to': '2026-10-21'})
        audit.action_sq_initialize()
        return audit

    def test_catalog_counts_idempotency(self):
        self.assertEqual(len(self.standard.item_ids), 48)
        self.assertEqual(self.standard.total_points, 1000)
        asm = self.env['sq.standard'].search([('sector', '=', 'ASM'), ('company_id', '=', self.env.company.id)])
        self.assertEqual(len(asm.item_ids), 36)
        self.assertEqual(asm.total_points, 1000)
        before = self.env['sq.item'].search([]).ids
        requirements = self.env['sq.doc.requirement'].search([('company_id', '=', self.env.company.id)])
        self.assertEqual(len(requirements), 467)
        self.assertFalse(requirements.filtered(lambda r: r.state != 'todo'))
        requirements[0].write({'note': '담당자 확인 중', 'state': 'progress'})
        self.env['sq.standard'].action_load_catalog()
        self.assertEqual(self.env['sq.item'].search([]).ids, before)
        self.assertEqual(requirements[0].state, 'progress')

    def test_start_uses_user_business_date_at_korean_morning_boundary(self):
        audit = self.assessment().with_context(tz='Asia/Seoul')
        with freeze_time('2026-10-21 22:20:00'):
            audit.action_start()
            self.assertEqual(str(audit.actual_date), '2026-10-22')
            self.assertEqual(audit.state, 'in_progress')
            utc_audit = self.assessment().with_context(tz='UTC')
            utc_audit.action_start()
            self.assertEqual(str(utc_audit.actual_date), '2026-10-21')

    def test_evidence_datetime_period_uses_local_calendar_day(self):
        audits = self.env['iatf.audit'].create([
            {'title': 'SQ timezone boundary %s' % n, 'planned_date': '2026-10-21',
             'company_id': self.env.company.id, 'lead_auditor_id': self.env.uid} for n in range(4)])
        for audit, stamp in zip(audits, ['2026-10-20 14:59:59', '2026-10-20 15:00:00',
                                        '2026-10-21 14:59:59', '2026-10-21 15:00:00']):
            self.env.cr.execute('UPDATE iatf_audit SET create_date=%s WHERE id=%s', [stamp, audit.id])
        audits.invalidate_recordset(['create_date'])
        rule = self.env['sq.evidence.rule'].create({
            'item_id': self.standard.item_ids[0].id, 'source_key': 'test.kst.day',
            'name': '한국 시간 일자 경계', 'model_name': 'iatf.audit', 'company_path': 'company_id',
            'date_field': 'create_date', 'domain_json': json.dumps([['id', 'in', audits.ids]])})
        target, domain = rule.with_context(tz='Asia/Seoul', sq_date_from='2026-10-21', sq_date_to='2026-10-21')._target()
        self.assertEqual(set(target.search(domain).ids), set(audits[1:3].ids))
        target, domain = rule.with_context(tz='UTC', sq_date_from='2026-10-21', sq_date_to='2026-10-21')._target()
        self.assertEqual(set(target.search(domain).ids), set(audits[2:].ids))
        rule.domain_json = json.dumps([['id', 'in', audits[:2].ids]])
        scoped = rule.with_context(sq_date_from='2026-10-21', sq_date_to='2026-10-21')
        self.assertEqual(scoped.with_context(tz='Asia/Seoul').evidence_count, 1)
        self.assertEqual(scoped.with_context(tz='UTC').evidence_count, 0)

    def test_evidence_date_period_is_not_timezone_shifted(self):
        audits = self.env['iatf.audit'].create([
            {'title': 'SQ calendar date %s' % day, 'planned_date': day, 'company_id': self.env.company.id,
             'lead_auditor_id': self.env.uid}
            for day in ('2026-10-20', '2026-10-21', '2026-10-22')])
        rule = self.env['sq.evidence.rule'].create({
            'item_id': self.standard.item_ids[0].id, 'source_key': 'test.kst.date',
            'name': '날짜 필드 일자 경계', 'model_name': 'iatf.audit', 'company_path': 'company_id',
            'date_field': 'planned_date', 'domain_json': json.dumps([['id', 'in', audits.ids]])})
        target, domain = rule.with_context(tz='Asia/Seoul', sq_date_from='2026-10-21', sq_date_to='2026-10-21')._target()
        self.assertEqual(target.search(domain), audits[1])

    def test_code_key_immutable(self):
        with self.assertRaises(UserError):
            self.standard.item_ids[0].write({'code': 'CHANGED'})

    def test_assessment_evidence_drilldown_keeps_period(self):
        line = self.assessment().sq_line_ids[0].with_context(tz='Asia/Seoul')
        records = self.env['iatf.audit'].create([
            {'title': 'Evidence drilldown %s' % day, 'planned_date': day,
             'lead_auditor_id': self.env.uid, 'company_id': self.env.company.id}
            for day in ('2026-10-20', '2026-10-21')])
        rule = self.env['sq.evidence.rule'].create({
            'item_id': line.item_id.id, 'source_key': 'test.drilldown.period',
            'name': '평가 기간 증빙', 'model_name': 'iatf.audit', 'company_path': 'company_id',
            'date_field': 'planned_date', 'domain_json': json.dumps([['id', 'in', records.ids]])})
        action = line.action_evidence()
        self.assertEqual(action['context']['sq_date_from'], '2026-10-21')
        self.assertEqual(action['context']['sq_date_to'], '2026-10-21')
        scoped = rule.with_context(action['context'])
        self.assertEqual(scoped.evidence_count, 1)
        source = scoped.action_open_source()
        self.assertEqual(self.env[source['res_model']].with_context(source['context']).search(source['domain']), records[1])
        self.assertFalse(source['context']['create'])
        self.assertFalse(source['context']['edit'])

    def test_score_na_and_snapshot(self):
        audit = self.assessment()
        audit.sq_line_ids.write({'rating': 'good', 'reason': '시험 판단 근거'})
        self.assertEqual(audit.sq_score, 1000)
        line = audit.sq_line_ids[0]
        line.write({'rating': 'na', 'reason': '담당자 해당없음 확인'})
        self.assertEqual(audit.sq_raw_score, 1000-line.points)
        self.assertEqual(audit.sq_score, 1000)
        self.standard.partial_ratio = 0.5
        line.write({'rating': 'partial'})
        self.assertEqual(line.score, line.points * 0.6)

    def test_unknown_cannot_finalize(self):
        audit = self.assessment()
        with self.assertRaises(UserError):
            audit.write({'state': 'report'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            audit.sq_line_ids[0].write({'rating': 'na'})

    def test_no_auto_pass_or_rating_overwrite(self):
        audit = self.assessment()
        line = audit.sq_line_ids[0]
        line.write({'rating': 'poor', 'reason': '심사자 판정'})
        audit.action_sq_propose()
        self.assertEqual(line.rating, 'poor')
        self.assertFalse(audit.sq_line_ids.filtered(lambda l: l.proposed_rating == 'good'))

    def test_self_assessment_is_not_its_own_evidence(self):
        audit = self.assessment()
        rule = self.env['sq.evidence.rule'].create({
            'item_id': self.standard.item_ids[0].id, 'source_key': 'self-audit-check',
            'name': '자체 평가 순환 참조 차단', 'model_name': 'iatf.audit',
            'company_path': 'company_id', 'domain_json': json.dumps([['id', '=', audit.id]])})
        self.assertEqual(rule._snapshot()['count'], 0)

    def test_frozen_assessment(self):
        audit = self.assessment()
        audit.sq_line_ids.write({'rating': 'partial', 'reason': '시험 보완사항'})
        approver = new_test_user(self.env, login='sq_freeze_approver',
                                groups='cams_sq.group_sq_user', email='sq-freeze@example.invalid')
        audit.write({'approval_line_ids': [(0, 0, {'user_id': approver.id})]})
        audit.action_submit_approval()
        audit.with_user(approver).action_approve_approval()
        audit.action_issue_report()
        with self.assertRaises(UserError):
            audit.sq_line_ids[0].write({'rating': 'good'})
        with self.assertRaises(UserError):
            audit.sq_line_ids[0].unlink()

    def test_company_evidence_and_access(self):
        other = self.env['res.company'].create({'name': 'SQ 격리 검증 회사'})
        rule = self.env['sq.evidence.rule'].create({'item_id': self.standard.item_ids[0].id,
            'name': '회사 격리 시험', 'source_key': 'test.company', 'model_name': 'iatf.audit',
            'company_path': 'company_id', 'date_field': 'planned_date'})
        own = self.env['iatf.audit'].create({'title': '같은 회사의 실제 감사', 'company_id': self.env.company.id,
            'planned_date': fields.Date.today(), 'lead_auditor_id': self.env.uid})
        foreign = self.env['iatf.audit'].create({'title': '다른 회사', 'company_id': other.id,
            'planned_date': fields.Date.today(), 'lead_auditor_id': self.env.uid})
        target, domain = rule._target()
        self.assertIn(own, target.search(domain))
        self.assertNotIn(foreign, target.search(domain))
        viewer = new_test_user(self.env, login='sq.test.viewer', groups='cams_sq.group_sq_user',
                               company_id=self.env.company.id, company_ids=[self.env.company.id])
        with self.assertRaises(UserError):
            self.env['sq.standard'].with_user(viewer).action_load_catalog()

    def test_missing_model_and_company_path_blocked(self):
        rule = self.env['sq.evidence.rule'].create({'item_id': self.standard.item_ids[0].id,
            'source_key': 'missing', 'name': '미연결', 'model_name': 'nonexistent.model'})
        self.assertTrue(rule._snapshot()['unavailable'])
        with self.assertRaises(UserError):
            rule.action_open_source()

    def test_no_domain_source_mutation_and_package(self):
        audit = self.assessment()
        before = self.env['stock.quant'].search_count([])
        result = audit.action_sq_package()
        self.assertTrue(self.env['sq.package'].search([], limit=1).data)
        self.assertEqual(result['type'], 'ir.actions.act_url')
        self.assertEqual(self.env['stock.quant'].search_count([]), before)

    def test_independent_app_menu(self):
        menu = self.env.ref('cams_sq.menu_sq_root')
        self.assertFalse(menu.parent_id)
        self.assertEqual(menu.name, 'SQ')

    def metric_fixture(self, values, kind='cpk', field='vda_score', **kwargs):
        records = self.env['iatf.audit']
        for value in values:
            records |= self.env['iatf.audit'].create({'title': '격리 회귀 지표 원천',
                'planned_date': '2026-10-21', 'lead_auditor_id': self.env.uid,
                'company_id': self.env.company.id, field: value})
        rule = self.env['sq.evidence.rule'].create(dict({'item_id': self.standard.item_ids[0].id,
            'source_key': 'test.metrics', 'name': '지표 회귀 시험', 'model_name': 'iatf.audit',
            'company_path': 'company_id', 'date_field': 'planned_date',
            'domain_json': json.dumps([['id', 'in', records.ids]]),
            'metric_kind': kind, 'metric_field': field, 'good_threshold': 1.33,
            'partial_threshold': 1, 'proposal_enabled': True, 'proposal_source': '격리 회귀 경계값 검증'}, **kwargs))
        return rule, records

    def test_cpk_metric_average_and_validation_gate(self):
        # Fixture field stores one decimal; use a representable boundary.
        rule, records = self.metric_fixture([1.0, 1.6], good_threshold=1.3)
        self.assertAlmostEqual(rule._metric_result()['value'], 1.3)
        self.assertEqual(rule._metric_result()['rating'], 'good')
        rule.proposal_enabled = False
        self.assertEqual(rule._metric_result()['rating'], 'unknown')
        rule.proposal_enabled = True
        rule.minimum_samples = 3
        self.assertEqual(rule._metric_result()['rating'], 'unknown')

    def test_grr_boundaries(self):
        rule, records = self.metric_fixture([10.0], 'grr', good_threshold=10, partial_threshold=30)
        self.assertEqual(rule._metric_result()['rating'], 'partial')
        records.vda_score = 30
        self.assertEqual(rule._metric_result()['rating'], 'partial')
        records.vda_score = 30.1
        self.assertEqual(rule._metric_result()['rating'], 'poor')
        records.vda_score = 9.9
        self.assertEqual(rule._metric_result()['rating'], 'good')
        records.vda_score = -1
        self.assertEqual(rule._metric_result()['rating'], 'unknown')

    def test_pass_rate_uses_decided_denominator_and_zero_unknown(self):
        rule, records = self.metric_fixture(['process', 'system', 'product'], 'pass_rate', 'audit_type',
            positive_values='process', decided_values='process,system', good_threshold=95, partial_threshold=0)
        result = rule._metric_result()
        self.assertEqual((result['value'], result['samples'], result['rating']), (50, 2, 'partial'))
        rule.domain_json = '[ ["id", "=", 0] ]'
        self.assertEqual(rule._metric_result()['rating'], 'unknown')

    def test_metric_acl_not_bypassed(self):
        rule, records = self.metric_fixture([1])
        rule.write({'model_name': 'ir.config_parameter', 'metric_kind': 'count'})
        viewer = new_test_user(self.env, login='sq.metric.viewer', groups='cams_sq.group_sq_user',
                              company_id=self.env.company.id, company_ids=[self.env.company.id])
        self.assertFalse(self.env['ir.config_parameter'].with_user(viewer).has_access('read'))
        self.assertTrue(rule.with_user(viewer)._metric_result()['unavailable'])

    def test_proposal_rpc_forgery_and_period_change(self):
        audit = self.assessment()
        with self.assertRaises(UserError):
            audit.sq_line_ids[0].write({'proposed_rating': 'good'})
        audit.action_sq_propose()
        self.assertTrue(audit.sq_line_ids[0].evidence_snapshot)
        audit.sq_date_from = '2026-10-01'
        self.assertFalse(audit.sq_line_ids[0].evidence_snapshot)
        self.assertEqual(audit.sq_line_ids[0].proposed_rating, 'unknown')
        with self.assertRaises(UserError):
            audit.write({'state': 'follow_up'})

    def test_package_original_attachment_safe_name_and_csv(self):
        audit = self.assessment()
        audit.sq_line_ids[0].reason = '=HYPERLINK("external")'
        attachment = self.env['ir.attachment'].create({'name': '../../evidence.txt',
            'raw': b'SQ test attachment', 'res_model': audit._name, 'res_id': audit.id,
            'company_id': self.env.company.id})
        audit.attachment_ids = attachment
        action = audit.action_sq_package()
        package = self.env['sq.package'].browse(int(action['url'].split('/')[4]))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(package.data))) as archive:
            paths = [p for p in archive.namelist() if p.startswith('attachments/')]
            self.assertEqual(len(paths), 1)
            self.assertNotIn('/../', paths[0])
            self.assertEqual(archive.read(paths[0]), b'SQ test attachment')
            self.assertIn("'=HYPERLINK", archive.read('assessment.csv').decode('utf-8-sig'))
            summary = json.loads(archive.read('summary.json'))
            self.assertEqual(summary['attachments'], 1)
            evidence = json.loads(archive.read('evidence.json'))
            self.assertTrue(any(e.get('sha256') for e in evidence))

    def test_criteria_shared_product_and_foreign_company(self):
        rule = self.env['sq.evidence.rule'].search([('model_name', '=', 'iatf.inspection.criteria'),
            ('company_id', '=', self.env.company.id)], limit=1)
        self.assertEqual(rule.company_path, 'product_id.company_id')
        rule.domain_json = '[]'
        own = self.env['product.product'].create({'name': '회사 공통 검사 기준 시험'})
        other = self.env['res.company'].create({'name': '다른 검사 기준 회사'})
        foreign = self.env['product.product'].create({'name': '타사 제품', 'company_id': other.id})
        criteria = self.env['iatf.inspection.criteria'].create([
            {'product_id': own.id, 'characteristic_name': '검증', 'specification': '시험'},
            {'product_id': foreign.id, 'characteristic_name': '검증', 'specification': '시험'}])
        model, domain = rule._target()
        found = model.search(domain)
        self.assertIn(criteria[0], found)
        self.assertNotIn(criteria[1], found)

    def test_uninstall_does_not_destroy_approval_history(self):
        from odoo.addons.cams_sq import uninstall_hook
        audit = self.assessment()
        with self.assertRaises(UserError):
            uninstall_hook(self.env)
        self.assertTrue(audit.exists())

    def test_closure_and_approval_metrics(self):
        rule, records = self.metric_fixture(['process', 'process', 'system'], 'closure', 'audit_type',
            positive_values=' process ', good_threshold=90, partial_threshold=60)
        self.assertAlmostEqual(rule._metric_result()['value'], 200 / 3)
        self.assertEqual(rule._metric_result()['rating'], 'partial')
        rule.write({'metric_kind': 'approval', 'good_threshold': 2, 'partial_threshold': 1})
        self.assertEqual(rule._metric_result()['value'], 2)
        self.assertEqual(rule._metric_result()['rating'], 'good')

    def test_metric_invalid_configuration(self):
        rule, records = self.metric_fixture([1])
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rule.write({'metric_kind': 'pass_rate', 'good_threshold': 101})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            rule.write({'proposal_source': '   '})

    def test_package_rejects_foreign_attachment(self):
        audit = self.assessment()
        other = self.env['res.company'].create({'name': '다른 첨부 회사'})
        attachment = self.env['ir.attachment'].create({'name': 'foreign.txt', 'raw': b'foreign confidential',
            'res_model': audit._name, 'res_id': audit.id, 'company_id': other.id})
        audit.attachment_ids = attachment
        action = audit.action_sq_package()
        package = self.env['sq.package'].browse(int(action['url'].split('/')[4]))
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(package.data))) as archive:
            self.assertFalse(any(p.startswith('attachments/') for p in archive.namelist()))
            self.assertIn('회사 범위 제한', archive.read('evidence.json').decode())

    def test_calibration_due_date_and_missing_are_not_auto_pass(self):
        equipment = self.env['iatf.measurement.equipment'].create({'name': '교정 지표 회귀 전용',
            'equipment_id_number': 'SQ-REGRESSION'})
        record = self.env['iatf.calibration.record'].create({'equipment_id': equipment.id,
            'result': 'pass', 'calibration_date': '2026-10-01', 'next_due_date': '2026-10-21'})
        rule = self.env['sq.evidence.rule'].create({'item_id': self.standard.item_ids[0].id,
            'source_key': 'test.calibration', 'name': '교정 기한 경계', 'model_name': record._name,
            'company_path': 'company_id', 'domain_json': json.dumps([['id', '=', record.id]]),
            'metric_kind': 'calibration', 'metric_field': 'next_due_date', 'good_threshold': 100,
            'partial_threshold': 0, 'positive_values': 'pass,adjusted',
            'proposal_enabled': True, 'proposal_source': '회귀 경계 검증'})
        # No period context: the explicit as-of day is tested by the current-day due date.
        record.next_due_date = fields.Date.context_today(rule)
        self.assertEqual(rule._metric_result()['rating'], 'good')
        record.next_due_date = '2020-01-01'
        self.assertEqual(rule._metric_result()['value'], 0)
        record.next_due_date = False
        self.assertEqual(rule._metric_result()['rating'], 'unknown')

    def test_installed_evidence_company_paths_complete(self):
        for rule in self.env['sq.evidence.rule'].search([('company_id', '=', self.env.company.id)]):
            if rule.model_name and rule.model_name in self.env:
                self.assertTrue(rule.company_path, rule.model_name)
                if rule.scope_mode == 'binding':
                    # A missing classification must be reported, never broadened to the company.
                    with self.assertRaisesRegex(UserError, '연결되지'):
                        rule._target()
                    continue
                target, domain = rule._target()
                target.search_count(domain)
                scoped = rule.with_context(sq_date_from='2026-10-01', sq_date_to='2026-10-21')
                self.assertFalse(scoped._snapshot().get('unavailable'), rule.model_name)

    def test_existing_audit_cannot_bypass_sq_workflow_by_type_change(self):
        ordinary = self.env['iatf.audit'].create({'title': '기존 일반 감사 보존 시험',
            'planned_date': fields.Date.today(), 'lead_auditor_id': self.env.uid})
        with self.assertRaises(UserError):
            ordinary.write({'audit_type': 'sq', 'sq_standard_id': self.standard.id, 'state': 'report'})
        self.assertNotEqual(ordinary.audit_type, 'sq')
