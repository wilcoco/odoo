"""Neutral sheet defaults are normal creation; source policy still needs a manager."""
import json

from odoo.exceptions import AccessError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


class SheetDefaultsFixture:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.worker = new_test_user(
            cls.env, login='r226-sheet-worker', lang='en_US',
            groups='base.group_user,iatf_work_environment.group_work_environment_user')
        cls.manager = new_test_user(
            cls.env, login='r226-sheet-manager',
            groups='base.group_user,iatf_work_environment.group_work_environment_manager')
        cls.Sheet = cls.env['iatf.check.sheet'].with_user(cls.worker)


@tagged('post_install', '-at_install')
class TestSheetDefaults(SheetDefaultsFixture, TransactionCase):
    def _assert_general(self, record):
        self.assertEqual(record.quality_purpose, 'general')
        self.assertFalse(record.layout_document_id)
        self.assertEqual(record.create_uid, self.worker)
        self.assertFalse(self.worker.has_group('iatf_work_environment.group_work_environment_manager'))

    def test_explicit_form_defaults_are_allowed(self):
        self._assert_general(self.Sheet.create({
            'name': 'SYNTHETIC R226 explicit', 'quality_purpose': 'general', 'layout_document_id': False}))

    def test_context_neutral_defaults_are_allowed(self):
        self._assert_general(self.Sheet.with_context(
            default_quality_purpose='general', default_layout_document_id=False
        ).create({'name': 'SYNTHETIC R226 context'}))

    def test_implicit_defaults_are_allowed(self):
        self._assert_general(self.Sheet.create({'name': 'SYNTHETIC R226 implicit'}))

    def test_non_neutral_values_and_context_are_rejected(self):
        for field, value in (('quality_purpose', 'lighting'), ('layout_document_id', 99999999)):
            for via_context in (False, True):
                with self.subTest(field=field, via_context=via_context):
                    sheet = self.Sheet.with_context(**{'default_' + field: value}) if via_context else self.Sheet
                    values = {'name': 'SYNTHETIC R226 rejected'}
                    if not via_context:
                        values[field] = value
                    with self.assertRaisesRegex(AccessError, '작업환경 책임자'), self.cr.savepoint():
                        sheet.create(values)

    def test_user_default_cannot_bypass_policy(self):
        self.env['ir.default'].set('iatf.check.sheet', 'quality_purpose', 'lighting', user_id=self.worker.id)
        with self.assertRaisesRegex(AccessError, '작업환경 책임자'), self.cr.savepoint():
            self.Sheet.create({'name': 'SYNTHETIC R226 user default'})
        # An explicitly neutral form value overrides the context/user default.
        self._assert_general(self.Sheet.with_context(default_quality_purpose='lighting').create({
            'name': 'SYNTHETIC R226 override', 'quality_purpose': 'general', 'layout_document_id': False}))

    def test_mixed_batch_is_rejected_before_any_create(self):
        before = self.Sheet.search_count([])
        with self.assertRaisesRegex(AccessError, '작업환경 책임자'), self.cr.savepoint():
            self.Sheet.create([
                {'name': 'SYNTHETIC R226 neutral batch', 'quality_purpose': 'general'},
                {'name': 'SYNTHETIC R226 restricted batch', 'quality_purpose': 'foolproof'},
            ])
        self.assertEqual(self.Sheet.search_count([]), before)

    def test_manager_still_creates_restricted_purpose(self):
        sheet = self.Sheet.with_user(self.manager).create({
            'name': 'SYNTHETIC R226 manager', 'quality_purpose': 'lighting'})
        self.assertEqual(sheet.quality_purpose, 'lighting')

    def test_existing_source_write_protection_is_unchanged(self):
        sheet = self.Sheet.create({'name': 'SYNTHETIC R226 ordinary edit'})
        sheet.write({'name': 'SYNTHETIC R226 renamed'})
        before = sheet.read(['name', 'quality_purpose', 'layout_document_id', 'revision'])
        for values in ({'quality_purpose': 'general'}, {'layout_document_id': False},
                       {'quality_purpose': 'lighting'}):
            with self.assertRaisesRegex(AccessError, '작업환경 책임자'), self.cr.savepoint():
                sheet.write(values)
        self.assertEqual(sheet.read(['name', 'quality_purpose', 'layout_document_id', 'revision']), before)


@tagged('post_install', '-at_install', 'r226_ui')
class TestSheetDefaultsBrowser(SheetDefaultsFixture, HttpCase):
    def test_worker_creates_general_sheet_in_form(self):
        name = 'SYNTHETIC R226 browser sheet'
        action = self.env.ref('iatf_work_environment.action_check_sheet')
        before = self.Sheet.search_count([])
        self.start_tour(
            '/odoo/action-%s' % action.id, 'work_environment_sheet_defaults_r226', login=self.worker.login,
            code='window.__r226SheetName = %s; odoo.startTour("work_environment_sheet_defaults_r226", {stepDelay: 0});'
                 % json.dumps(name))
        self.env.invalidate_all()
        record = self.Sheet.search([('name', '=', name)])
        self.assertEqual(len(record), 1)
        self.assertEqual(self.Sheet.search_count([]), before + 1)
        self.assertEqual(record.create_uid, self.worker)
        self.assertEqual(record.quality_purpose, 'general')
        self.assertFalse(record.layout_document_id)
