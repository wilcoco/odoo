from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged, new_test_user


@tagged('post_install', '-at_install')
class TestSqDaily(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()
        cls.item = cls.env['sq.item'].search([('code', '=', 'INJ.3_1'), ('company_id', '=', cls.env.company.id)], limit=1)
        # An upgraded customer clone already has plans and bindings. Isolate the
        # fixture without removing or changing those existing business records.
        cls.item = cls.item.copy({'code': 'TEST.DAILY', 'name': '[TEST] daily item'})
        cls.today = fields.Date.context_today(cls.env.user)
        cls.role = cls.env['ops.role'].create({'name': '[TEST] SQ daily'})
        cls.sheet = cls.env['iatf.check.sheet'].create({'name': '[TEST] daily direct',
            'company_id': cls.env.company.id, 'start_date': cls.today,
            'item_ids': [(0, 0, {'name': '압력 확인', 'standard': '승인된 기준', 'entry_type': 'judge'})]})
        cls.env['sq.evidence.binding'].create({'item_id': cls.item.id,
            'source_ref': 'iatf.check.sheet,%s' % cls.sheet.id, 'purpose': 'TEST required sheet'})
        groups = ('cams_ops_process.group_ops_manager,cams_sq.group_sq_manager,'
                  'iatf_work_environment.group_work_environment_manager,iatf_nonconformity.group_nc_manager')
        cls.operator = new_test_user(cls.env, login='sq.daily.operator', groups=groups)
        cls.approver = new_test_user(cls.env, login='sq.daily.approver', groups=groups)

    def plan(self, **extra):
        values = {'name': '[TEST] direct checklist plan', 'role_id': self.role.id,
            'periodicity': 'daily', 'sq_item_id': self.item.id, 'sq_start_date': self.today,
            'due_days': 0, 'requires_approval': True, 'sq_sheet_ids': [(6, 0, self.sheet.ids)]}
        values.update(extra)
        return self.env['ops.task.def'].create(values)

    def check(self, result='ok', sheet=None, done=True, day=None):
        sheet = sheet or self.sheet
        record = self.env['iatf.check.record'].create({'sheet_id': sheet.id,
            'company_id': sheet.company_id.id, 'check_date': day or self.today,
            'line_ids': [(0, 0, {'item_id': sheet.item_ids[:1].id, 'item_name': '압력 확인', 'result': result})]})
        if done:
            record.action_done()
        return record

    def task(self, check=None, **values):
        plan = self.plan()
        task = plan._create_task(str(self.today), self.today)
        task.write(dict({'sq_performed_date': self.today, 'sq_result': 'ok',
                         'done_note': '[TEST] actual existing source',
                         'sq_check_ids': [(6, 0, (check or self.check()).ids)]}, **values))
        return task

    def nc(self):
        return self.env['iatf.nonconformity'].create({'title': '[TEST] abnormal daily check',
            'company_id': self.env.company.id, 'containment_action': '격리', 'root_cause': '원인 확인'})

    def close_nc(self, nc):
        nc.action_start_containment(); nc.action_start_analysis(); nc.action_start_corrective()
        ca = self.env['iatf.corrective.action'].create({'nonconformity_id': nc.id,
            'description': '조정 및 재점검', 'verification_result': '실측 재확인', 'effective': 'yes'})
        ca.action_start(); ca.action_implement(); ca.action_verify()
        nc.action_start_verification(); nc.action_close()

    def test_direct_record_without_duplicate_document_or_audit(self):
        task = self.task()
        documents = self.env['iatf.document'].search_count([])
        audits = self.env['iatf.audit'].search_count([])
        checks = task.sq_check_ids.read(['state', 'overall_result', 'snapshot_count'])
        task.with_user(self.operator).action_mark_done()
        self.assertEqual(task.state, 'done')
        with self.assertRaises(AccessError):
            task.with_user(self.operator).action_approve()
        task.with_user(self.approver).action_approve()
        self.assertEqual(task.state, 'approved')
        self.assertEqual(documents, self.env['iatf.document'].search_count([]))
        self.assertEqual(audits, self.env['iatf.audit'].search_count([]))
        self.assertEqual(checks, task.sq_check_ids.read(['state', 'overall_result', 'snapshot_count']))
        with self.assertRaises(UserError):
            task.write({'sq_check_ids': [(5, 0, 0)]})

    def test_assigned_approver_without_ops_manager_can_recall_and_approve(self):
        groups = 'cams_sq.group_sq_user,iatf_work_environment.group_work_environment_user'
        operator = new_test_user(self.env, login='sq.role.worker', groups=groups)
        approver = new_test_user(self.env, login='sq.role.approver', groups=groups)
        self.role.user_ids = operator
        approval_role = self.env['ops.role'].create({'name': '[TEST] approval only',
                                                    'user_ids': [(6, 0, approver.ids)]})
        task = self.task()
        task.task_def_id.approver_role_id = approval_role
        self.assertFalse(approver.has_group('cams_ops_process.group_ops_manager'))
        task.with_user(operator).action_mark_done()
        with self.assertRaises(AccessError): task.with_user(operator).action_reset_todo()
        task.with_user(approver).action_reset_todo()
        self.assertEqual(task.state, 'todo')
        task.with_user(operator).action_mark_done()
        task.with_user(approver).action_approve()
        self.assertEqual(task.state, 'approved')
        self.assertEqual(task.approve_uid, approver)
        self.assertTrue(task.with_user(approver).message_ids)
        with self.assertRaises(UserError): task.with_user(approver).write({'done_note': 'tamper'})

    def test_sq_approver_does_not_gain_unrelated_or_regular_ops_access(self):
        approver = new_test_user(self.env, login='sq.role.unrelated', groups='cams_sq.group_sq_user')
        task = self.task()
        with self.assertRaises(AccessError): task.with_user(approver).read(['state'])
        with self.assertRaises(AccessError): task.with_user(approver).write({'done_note': 'not assigned'})
        approval_role = self.env['ops.role'].create({'name': '[TEST] regular approver',
                                                    'user_ids': [(6, 0, approver.ids)]})
        regular = self.env['ops.task.def'].create({'name': '[TEST] non SQ',
            'role_id': self.role.id, 'approver_role_id': approval_role.id})
        regular_task = regular._create_task(str(self.today), self.today)
        with self.assertRaises(AccessError): regular_task.with_user(approver).read(['state'])

    def test_draft_old_and_unbound_checks_rejected(self):
        task = self.task(self.check(done=False))
        with self.assertRaises(UserError): task.action_mark_done()
        task.sq_check_ids = self.check(day=self.today - timedelta(days=1))
        with self.assertRaises(UserError): task.action_mark_done()
        other = self.env['iatf.check.sheet'].create({'name': '[TEST] unrelated'})
        task.sq_check_ids = self.check(sheet=other)
        with self.assertRaises(UserError): task.action_mark_done()

    def test_required_sheets_cannot_be_silently_omitted(self):
        task = self.task()
        task.sq_check_ids = False
        with self.assertRaises(UserError): task.action_mark_done()
        with self.assertRaises(UserError): task.task_def_id.write({'sq_sheet_ids': [(5, 0, 0)]})

    def test_ng_cannot_be_reported_as_ok_or_closed_without_recheck(self):
        ng = self.check('ng')
        task = self.task(ng)
        with self.assertRaises(UserError): task.action_mark_done()
        nc = self.nc()
        task.write({'sq_result': 'ng', 'sq_nonconformity_id': nc.id})
        task.with_user(self.operator).action_mark_done()
        with self.assertRaises(UserError): task.with_user(self.approver).action_approve()
        self.close_nc(nc)
        with self.assertRaises(UserError): task.with_user(self.approver).action_approve()
        task.with_user(self.approver).action_reset_todo()
        task.sq_recheck_ids = self.check()
        task.with_user(self.operator).action_mark_done()
        task.with_user(self.approver).action_approve()
        self.assertEqual(task.state, 'approved')
        self.assertEqual(task.sq_result, 'ng')
        self.assertEqual(ng.overall_result, 'issue')
        self.assertEqual(ng.snapshot_count, 1)

    def test_recheck_must_repeat_failed_item_not_only_other_ok(self):
        task = self.task(self.check('ng'), sq_result='ng')
        nc = self.nc(); self.close_nc(nc)
        task.sq_nonconformity_id = nc
        recheck = self.check(done=False)
        recheck.line_ids.write({'item_id': False, 'item_name': '다른 항목'})
        recheck.action_done(); task.sq_recheck_ids = recheck
        task.with_user(self.operator).action_mark_done()
        with self.assertRaises(UserError): task.with_user(self.approver).action_approve()

    def test_completed_source_changed_after_report_requires_recall(self):
        task = self.task()
        task.with_user(self.operator).action_mark_done()
        task.sq_check_ids.action_draft()
        task.sq_check_ids.action_done()
        with self.assertRaises(UserError): task.with_user(self.approver).action_approve()
        self.assertEqual(task.state, 'done')

    def test_other_company_source_and_company_task_isolation(self):
        task = self.task()
        company = self.env['res.company'].create({'name': '[TEST] foreign daily'})
        sheet = self.env['iatf.check.sheet'].create({'name': '[TEST] foreign', 'company_id': company.id})
        foreign = self.check(sheet=sheet)
        with self.assertRaises(UserError), self.cr.savepoint():
            task.sq_check_ids = foreign
        with self.assertRaises(AccessError):
            task.with_user(self.operator).with_context(allowed_company_ids=[company.id]).read(['sq_result'])

    def test_source_read_permission_is_not_bypassed(self):
        user = new_test_user(self.env, login='sq.daily.no.source',
            groups='cams_sq.group_sq_user,cams_ops_process.group_ops_manager')
        task = self.task()
        with self.assertRaises(AccessError): task.with_user(user).action_mark_done()
        self.assertEqual(task.state, 'todo')

    def test_missing_periods_and_late_generation_keep_original_deadline(self):
        start = self.today - timedelta(days=3)
        plan = self.plan(sq_start_date=start)
        ctx = {'sq_date_from': str(start), 'sq_date_to': str(self.today)}
        self.assertEqual(self.item.with_context(**ctx)._daily_snapshot()['missing'], 4)
        task = plan._create_task(str(start), self.today)
        self.assertEqual(task.scheduled_date, start)
        self.assertEqual(task.due_date, start)
        self.assertFalse(plan._create_task(str(start), self.today))
        snap = self.item.with_context(**ctx)._daily_snapshot()
        self.assertEqual(snap['missing'], 3); self.assertEqual(snap['overdue'], 1)

    def test_archived_plan_does_not_hide_past_missing_work(self):
        start = self.today - timedelta(days=2)
        plan = self.plan(sq_start_date=start)
        plan.write({'sq_end_date': self.today, 'active': False})
        snap = self.item.with_context(sq_date_from=str(start), sq_date_to=str(self.today))._daily_snapshot()
        self.assertEqual(snap['missing'], 3)
        with self.assertRaises(UserError): plan.write({'sq_end_date': start})

    def test_restricted_view_does_not_claim_zero_missing_and_adhoc_not_guessed(self):
        viewer = new_test_user(self.env, login='sq.daily.reader', groups='cams_sq.group_sq_user')
        snap = self.item.with_user(viewer)._daily_snapshot()
        self.assertTrue(snap['restricted']); self.assertIn('미확인', snap['status'])
        self.plan(periodicity='adhoc')
        self.assertEqual(self.item._daily_snapshot()['missing'], 0)

    def test_no_plan_is_unconfigured_not_good_and_window_bounded(self):
        self.assertEqual(self.item._daily_snapshot()['status'], '관리계획 미설정')
        with self.assertRaises(UserError):
            self.item.with_context(sq_date_from='2020-01-01', sq_date_to='2026-01-01')._daily_snapshot()

    def test_shift_check_cannot_cover_another_shift(self):
        self.sheet.cycle = 'shift'
        with self.assertRaises(UserError), self.cr.savepoint(): self.plan()
        plan = self.plan(sq_shift='evening')
        task = plan._create_task(str(self.today), self.today)
        task.write({'sq_performed_date': self.today, 'sq_result': 'ok', 'done_note': '야간 점검',
                    'sq_check_ids': [(6, 0, self.check().ids)]})
        with self.assertRaises(UserError): task.action_mark_done()
        check = self.check(done=False); check.shift = 'evening'; check.action_done()
        task.sq_check_ids = check
        task.with_user(self.operator).action_mark_done()
        task.with_user(self.approver).action_approve()
        self.assertEqual(task.state, 'approved')

    def test_closed_nc_without_effective_action_is_not_closed_loop(self):
        task = self.task(self.check('ng'), sq_result='ng')
        nc = self.nc(); nc.action_close()
        task.write({'sq_nonconformity_id': nc.id, 'sq_recheck_ids': [(6, 0, self.check().ids)]})
        task.with_user(self.operator).action_mark_done()
        with self.assertRaises(UserError): task.with_user(self.approver).action_approve()

    def test_ok_record_completed_before_ng_is_not_a_recheck(self):
        old_ok = self.check()
        task = self.task(self.check('ng'), sq_result='ng')
        nc = self.nc(); self.close_nc(nc)
        task.write({'sq_nonconformity_id': nc.id, 'sq_recheck_ids': [(6, 0, old_ok.ids)]})
        task.with_user(self.operator).action_mark_done()
        with self.assertRaises(UserError): task.with_user(self.approver).action_approve()

    def test_sq_manager_reads_sq_across_roles_without_general_ops_write(self):
        manager = new_test_user(self.env, login='sq.daily.only.sq.manager',
            groups='cams_sq.group_sq_manager,iatf_work_environment.group_work_environment_user')
        task = self.task()
        other_role = self.env['ops.role'].create({'name': '[TEST] unrelated private role'})
        regular = self.env['ops.task.def'].create({'name': '[TEST] unrelated private plan', 'role_id': other_role.id})
        self.assertTrue(task.with_user(manager).read(['done_note']))
        self.assertEqual(self.item.with_user(manager)._daily_snapshot()['plans'], 1)
        self.assertTrue(self.role.with_user(manager).read(['name']))
        with self.assertRaises(AccessError): regular.with_user(manager).read(['name'])
        with self.assertRaises(AccessError): other_role.with_user(manager).read(['name'])
        with self.assertRaises(AccessError), self.cr.savepoint(): task.with_user(manager).write({'done_note': 'not assigned'})
        with self.assertRaises(AccessError), self.cr.savepoint(): task.task_def_id.with_user(manager).write({'name': 'not manager'})
        with self.assertRaises(AccessError): task.with_user(manager).action_mark_done()

    def test_sq_read_scope_still_rejects_other_company(self):
        company = self.env['res.company'].create({'name': '[TEST] second SQ company'})
        self.env['sq.standard'].with_company(company).action_load_catalog()
        other = self.env['sq.item'].search([('company_id', '=', company.id)], limit=1)
        plan = self.env['ops.task.def'].with_company(company).create({'name': '[TEST] foreign plan',
            'role_id': self.role.id, 'periodicity': 'daily', 'sq_item_id': other.id,
            'sq_start_date': self.today, 'requires_approval': True})
        task = plan._create_task(str(self.today), self.today)
        manager = new_test_user(self.env, login='sq.daily.single.company.manager', groups='cams_sq.group_sq_manager')
        with self.assertRaises(AccessError): plan.with_user(manager).read(['name'])
        with self.assertRaises(AccessError): task.with_user(manager).read(['done_note'])
