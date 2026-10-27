import base64
import collections
import io
import json
import zipfile
from datetime import timedelta
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user
from odoo.exceptions import AccessError, UserError
from ..models.specs import SPECS


@tagged('post_install', '-at_install')
class TestOutputs(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()
        cls.env['sq.standard'].action_load_union()
        cls.env['sq.doc.requirement'].action_load_outputs()
        cls.today = fields.Date.context_today(cls.env['sq.doc.requirement'])
        cls.req = cls.env['sq.doc.requirement'].search([('company_id', '=', cls.env.company.id), ('output_type', '=', 'report')], limit=1)
        cls.req.write({'output_model': 'iatf.check.record'})
        cls.sheet = cls.env['iatf.check.sheet'].create({'name': 'UT-OUTPUT 점검', 'code': 'UT-OUTPUT',
            'company_id': cls.env.company.id, 'target_type': 'facility', 'cycle': 'daily',
            'item_ids': [(0, 0, {'name': '실측 온도', 'check_method': 'measure', 'spec_min': 10, 'spec_max': 20, 'standard': '10~20'})]})
        cls.env['sq.output.binding'].create({'requirement_id': cls.req.id,
            'source_ref': '%s,%s' % (cls.sheet._name, cls.sheet.id), 'purpose': '같은 호퍼의 실제 온도 점검'})
        cls.record = cls.env['iatf.check.record'].create({'sheet_id': cls.sheet.id, 'check_date': cls.today})
        cls.record.line_ids.write({'value': 15})
        cls.wizard = cls.env['sq.output.wizard'].create({'requirement_ids': [(6, 0, cls.req.ids)],
            'date_from': cls.today, 'date_to': cls.today})

    def test_01_catalog_idempotent_and_alias_sector(self):
        requirements = self.env['sq.doc.requirement'].search([('company_id', '=', self.env.company.id)])
        self.assertEqual(collections.Counter(requirements.mapped('output_type')),
            {'report': 244, 'upload': 207, 'external': 7, 'export': 9})
        before = requirements.read(['state', 'document_ids', 'note', 'output_model'])
        self.env['sq.doc.requirement'].action_load_outputs()
        self.assertEqual(requirements.read(['state', 'document_ids', 'note', 'output_model']), before)
        aliases = self.env['sq.item.alias'].search([('company_id', '=', self.env.company.id), ('revision', '=', 'OURS-36')])
        self.assertEqual(len(aliases), 36)
        self.assertTrue(all(item.code.startswith('ASM.') for item in aliases.item_id))
        union = self.env['sq.standard'].search([('company_id', '=', self.env.company.id), ('sector', '=', 'INJ'), ('revision', '=', '2026-10-union')])
        self.assertEqual((union.total_points, union.scored_points), (1030, 1010))

    def test_02_bound_record_and_period_no_other_sources(self):
        before = self.record.read(['state', 'write_date', 'write_uid'])
        self.assertEqual(self.req._output_records(self.today, self.today), self.record)
        self.assertFalse(self.req._output_records(self.today - timedelta(days=2), self.today - timedelta(days=1)))
        data = self.wizard._payloads()[0]
        self.assertEqual(data['rows'][0]['id'], self.record.id)
        self.assertIn('검토 서명 없음', data['rows'][0]['signatures'])
        self.assertIn('미완료', data['warning'])
        self.assertEqual(self.record.read(['state', 'write_date', 'write_uid']), before)

    def test_03_source_acl_not_sudo(self):
        user = new_test_user(self.env, login='sq_output_reader', groups='base.group_user,cams_sq.group_sq_user')
        wizard = self.env['sq.output.wizard'].with_user(user).create({'requirement_ids': [(6, 0, self.req.ids)],
            'date_from': self.today, 'date_to': self.today})
        payload = wizard._payloads()[0]
        self.assertFalse(payload['rows'])
        self.assertIn('권한', payload['warning'])
        with self.assertRaises(AccessError):
            self.req.with_user(user).write({'output_model': 'iatf.document'})

    def test_04_company_binding_rejected(self):
        company = self.env['res.company'].create({'name': 'UT output other company'})
        sheet = self.sheet.copy({'code': 'UT-OUTPUT-OTHER', 'company_id': company.id})
        with self.assertRaises(AccessError):
            self.env['sq.output.binding'].create({'requirement_id': self.req.id,
                'source_ref': '%s,%s' % (sheet._name, sheet.id), 'purpose': '잘못된 회사 연결'})

    def test_05_multiple_same_day_and_html_escape(self):
        extra = self.env['iatf.check.record'].create({'sheet_id': self.sheet.id, 'check_date': self.today})
        extra.line_ids.write({'value': 19})
        self.req.name = '<script>not executable</script>'
        data = self.wizard._payloads()[0]
        self.assertEqual(len(data['rows']), 2)
        self.assertIn('15', data['grids'][0]['rows'][0]['values'][0])
        self.assertIn('19', data['grids'][0]['rows'][0]['values'][0])
        html, unused = self.env['ir.actions.report']._render_qweb_html('cams_sq_outputs.report_output', self.wizard.ids)
        self.assertIn(b'&lt;script&gt;', html)
        self.assertNotIn(b'<script>not executable', html)

    def test_06_xlsx_literal_and_source_content(self):
        self.req.name = '=HYPERLINK("https://example.invalid")'
        raw = self.wizard._xlsx()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            xml = archive.read('xl/worksheets/sheet1.xml')
            self.assertNotIn(b'<f>', xml)
            self.assertIn(b'15', archive.read('xl/sharedStrings.xml'))

    def upload(self, files):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name, raw in files:
                archive.writestr(name, raw)
        category = self.env['iatf.document.category'].search([], limit=1)
        if not category:
            category = self.env['iatf.document.category'].create({'name': 'UT', 'code': 'UTOUTPUT'})
        return self.env['sq.output.upload'].create({'category_id': category.id, 'archive': base64.b64encode(stream.getvalue())})

    def test_07_upload_repetition_no_approval(self):
        req = self.env['sq.doc.requirement'].search([('company_id', '=', self.env.company.id), ('output_type', '=', 'upload')], limit=1)
        before = req.document_ids
        wizard = self.upload([(req.source_key + '/actual.txt', b'actual business source')])
        wizard.action_import(); created = req.document_ids - before
        self.assertEqual(len(created), 1)
        self.assertEqual(created.state, 'draft')
        self.assertNotEqual(req.state, 'ready')
        wizard.action_import()
        self.assertEqual(req.document_ids - before, created)
        self.upload([(req.source_key + '/actual.txt', b'corrected source')]).action_import()
        self.assertEqual(len(req.document_ids - before), 2)
        self.assertEqual(created.attachment_ids.raw, b'actual business source')

    def test_08_upload_atomic_bad_key_and_traversal(self):
        req = self.env['sq.doc.requirement'].search([('company_id', '=', self.env.company.id), ('output_type', '=', 'upload')], limit=1)
        before = req.document_ids
        for suffix in ('../escape.txt', 'UNKNOWN/file.txt'):
            wizard = self.upload([(req.source_key + '/good.txt', b'valid'), (suffix, b'bad')])
            with self.assertRaises(UserError):
                wizard.action_import()
            self.assertEqual(req.document_ids, before)

    def test_09_unbound_is_missing_not_ready(self):
        self.req.output_binding_ids.unlink()
        payload = self.wizard._payloads()[0]
        self.assertFalse(payload['rows'])
        self.assertIn('연결', payload['warning'])
        self.assertNotEqual(self.req.state, 'ready')

    def test_10_all_installed_adapter_boundaries(self):
        errors = []
        for name, spec in SPECS.items():
            if name not in self.env:
                continue
            model = self.env[name]
            missing = [key for key in spec['columns'] if key not in model._fields]
            errors.extend(name + ':column=' + key for key in missing)
            if spec['lines']:
                relation, columns = spec['lines']
                field = model._fields.get(relation)
                if not field or field.type not in ('one2many', 'many2many'):
                    errors.append(name + ':lines=' + relation)
                else:
                    errors.extend(name + ':detail=' + key for key in columns.split() if key not in self.env[field.comodel_name]._fields)
            for target, path in spec['scopes'].items():
                field = model._fields.get(path)
                if not field or field.comodel_name != target:
                    errors.append(name + ':scope=' + path)
            if spec['date'] and (spec['date'] not in model._fields or model._fields[spec['date']].type not in ('date', 'datetime')):
                errors.append(name + ':date=' + str(spec['date']))
            current = model
            for part in spec['company'].split('.'):
                field = current._fields.get(part)
                if not field or field.type != 'many2one':
                    errors.append(name + ':company=' + spec['company']); break
                current = self.env[field.comodel_name]
            else:
                if current._name != 'res.company': errors.append(name + ':company target')
        self.assertFalse(errors, '\n'.join(errors))

    def test_11_point_score_actual_and_revision_preserved(self):
        self.sheet.item_ids.write({'five_point_required': True, 'five_point_definition': '5 정상 / 1~2 책임자 보고 후 가동중지', 'stop_score': '2'})
        self.assertFalse(self.record.line_ids.five_point_required)
        record = self.env['iatf.check.record'].create({'sheet_id': self.sheet.id, 'check_date': self.today,
            'trace_exception': '격리 기능시험의 점수·완료 보존 확인'})
        record.line_ids.write({'value': 15})
        with self.assertRaises(UserError):
            record.action_done()
        record.line_ids.five_point_score = '2'
        self.assertEqual(record.overall_result, 'issue')
        record.corrective_action = '시험 조치: 관리책임자 보고·가동 중지 확인'
        record.action_done()
        snapshot = record.snapshot_ids[-1].content
        self.assertEqual(json.loads(snapshot)[0]['실제점수'], '2')
        with self.assertRaises(UserError):
            record.line_ids.five_point_score = '5'
        self.sheet.item_ids.stop_score = '1'
        self.assertEqual(record.line_ids.stop_score, '2')
        self.assertEqual(record.snapshot_ids[-1].content, snapshot)

    def test_12_package_contents_and_deficiency_visible(self):
        standard = self.env['sq.standard'].search([('sector', '=', 'INJ'), ('revision', '=', '2026-10-union'), ('company_id', '=', self.env.company.id)], limit=1)
        audit = self.env['iatf.audit'].create({'title': 'UT output package', 'audit_type': 'sq',
            'planned_date': self.today, 'lead_auditor_id': self.env.uid, 'company_id': self.env.company.id,
            'sq_standard_id': standard.id, 'sq_date_from': self.today, 'sq_date_to': self.today})
        audit.action_sq_initialize()
        # XLSX keeps this regression independent of wkhtmltopdf availability.
        self.req.write({'output_format': 'xlsx'})
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            audit._sq_package_outputs(archive, 100 * 1024**2)
        with zipfile.ZipFile(io.BytesIO(stream.getvalue())) as archive:
            self.assertIn('00_목차.csv', archive.namelist())
            self.assertIn('99_미비/미비목록.csv', archive.namelist())
            self.assertTrue(any(name.endswith('.xlsx') for name in archive.namelist()))
            self.assertIn('연결', archive.read('99_미비/미비목록.csv').decode('utf-8-sig'))
        self.assertNotEqual(self.req.state, 'ready')

    def test_13_coverage_requires_binding_and_approved_actual(self):
        rule = self.env['sq.evidence.rule'].search([('source_key', '=', 'union-INJ.1_4-coverage'), ('company_id', '=', self.env.company.id)])
        self.assertEqual(len(rule), 1)
        self.assertFalse(rule.proposal_enabled)
        saturday = self.today - timedelta(days=(self.today.weekday() - 5) % 7)
        rule = rule.with_context(sq_date_from=str(saturday), sq_date_to=str(saturday + timedelta(days=1)))
        with self.assertRaises(UserError):
            rule._target()
        role = self.env['ops.role'].create({'name': 'UT coverage role'})
        definition = self.env['ops.task.def'].create({'name': 'UT 주말 실제 점검', 'role_id': role.id,
            'company_id': self.env.company.id, 'sq_coverage_kind': 'weekend', 'periodicity': 'adhoc', 'requires_approval': True})
        self.env['sq.evidence.binding'].create({'item_id': rule.item_id.id, 'source_ref': 'ops.task.def,%d' % definition.id,
            'purpose': '실제 주말 점검 정의'})
        task = self.env['ops.task'].create({'task_def_id': definition.id, 'scheduled_date': saturday,
            'period_key': 'UT coverage', 'state': 'done', 'done_date': str(saturday) + ' 03:00:00',
            'done_uid': self.env.uid, 'done_note': '격리 시험용 실제 입력 역할 검증'})
        target, domain = rule._target()
        self.assertNotIn(task, target.search(domain))
        task.write({'state': 'approved', 'approve_uid': self.env.uid, 'approve_date': str(saturday) + ' 04:00:00'})
        self.assertIn(task, target.search(domain))
        task.scheduled_date = saturday - timedelta(days=1)
        self.assertNotIn(task, target.search(rule._target()[1]))
        with self.assertRaises(UserError):
            definition.sq_coverage_kind = 'overtime'

    def test_14_existing_upload_tamper_not_silently_reused(self):
        req = self.env['sq.doc.requirement'].search([('company_id', '=', self.env.company.id), ('output_type', '=', 'upload')], limit=1)
        wizard = self.upload([(req.source_key + '/source.txt', b'original')])
        wizard.action_import()
        doc = req.document_ids.filtered('sq_upload_key')
        doc.attachment_ids.raw = b'edited outside import'
        with self.assertRaises(UserError):
            wizard.action_import()

    def test_15_native_reports_reuse_and_reject_unbound(self):
        from ..models.output import NATIVE_REPORTS
        for model, xmlid in NATIVE_REPORTS.items():
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action:
                self.assertEqual(action.model, model)
        with self.assertRaises(UserError):
            self.wizard.action_native_pdf()
        self.req.write({'output_model': 'iatf.control.plan'})
        self.req.output_binding_ids.unlink()
        with self.assertRaises(UserError):
            self.wizard.action_native_pdf()
