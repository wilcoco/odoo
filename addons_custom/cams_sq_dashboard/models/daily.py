"""Read existing plans and evidence; do not create a second daily ledger."""
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class SqDailyItem(models.Model):
    _inherit = 'sq.item'

    daily_status = fields.Char('일상관리 확인', compute='_compute_daily')
    daily_plan_count = fields.Integer('관리계획', compute='_compute_daily')
    daily_missing_count = fields.Integer('미생성 업무', compute='_compute_daily')
    daily_overdue_count = fields.Integer('기한 초과 업무', compute='_compute_daily')
    daily_sheet_overdue = fields.Integer('점검 미실시 항목', compute='_compute_daily')
    daily_pending_ng = fields.Integer('NG 후속 미승인', compute='_compute_daily')
    daily_period = fields.Char('조회 기간', compute='_compute_daily')
    daily_document_status = fields.Char('연결 문서 확인', compute='_compute_documents')
    daily_document_review_due = fields.Integer('검토기한 경과 문서', compute='_compute_documents')
    daily_document_unapproved = fields.Integer('미승인·폐기 문서', compute='_compute_documents')

    def _document_snapshot(self):
        self.ensure_one()
        self.check_access('read')
        documents = self.env['iatf.document'].browse(self._bound_source_ids('iatf.document')).exists()
        documents.check_access('read')
        today = fields.Date.context_today(self)
        due = documents.filtered(lambda d: (d.next_review_date and d.next_review_date < today)
                                 or (d.state == 'approved' and not d.quality_evidence_current))
        unapproved = documents.filtered(lambda d: d.state != 'approved')
        return dict(total=len(documents), due=len(due), unapproved=len(unapproved),
            status='연결 문서 없음' if not documents else '문서 검토 필요' if due or unapproved else '연결 문서 상태 확인 · 내용 적합 판정 아님')

    @api.depends_context('uid', 'allowed_company_ids', 'tz')
    def _compute_documents(self):
        for item in self:
            try:
                data = item._document_snapshot()
            except AccessError:
                data = dict(status='문서 조회 권한 부족', due=0, unapproved=0)
            item.daily_document_status = data['status']
            item.daily_document_review_due = data['due']
            item.daily_document_unapproved = data['unapproved']

    def action_daily_documents(self):
        self.ensure_one()
        self.check_access('read')
        self.env['iatf.document'].check_access('read')
        return {'type': 'ir.actions.act_window', 'name': self.code + ' 연결 문서',
                'res_model': 'iatf.document', 'view_mode': 'list,form',
                'domain': [('id', 'in', self._bound_source_ids('iatf.document'))],
                'context': dict(self.env.context, create=False, edit=False, delete=False)}

    def _daily_window(self):
        today = fields.Date.context_today(self)
        start = fields.Date.to_date(self.env.context.get('sq_date_from')) or today.replace(day=1)
        end = fields.Date.to_date(self.env.context.get('sq_date_to')) or today
        if end < start or (end - start).days > 366:
            raise UserError(_('일상관리 조회 기간은 시작일 이후 최대 367일로 지정하십시오.'))
        return start, end, today

    def _daily_snapshot(self):
        self.ensure_one()
        self.check_access('read')
        start, end, today = self._daily_window()
        result = dict(period='%s ~ %s' % (start, end), plans=0, missing=0, overdue=0, sheet_overdue=0, ng=0)
        # A role-filtered task search cannot prove that another role has no task.
        # Only managers can perform full-plan reconciliation; never sudo it.
        if not (self.env.su or self.env.user.has_group('cams_ops_process.group_ops_manager')
                or self.env.user.has_group('cams_sq.group_sq_manager')):
            return dict(result, status='집계 미확인: SQ 관리자 또는 운영 관리자 조회 권한 필요', restricted=True)
        if not all(self.env[m].has_access('read') for m in
                   ('ops.task.def', 'ops.task', 'iatf.check.sheet', 'iatf.check.sheet.item')):
            return dict(result, status='집계 미확인: 원천 읽기 권한 필요', restricted=True)
        definitions = self.env['ops.task.def'].with_context(active_test=False).search([
            ('sq_item_id', '=', self.id), ('sq_start_date', '<=', end),
            '|', ('sq_end_date', '=', False), ('sq_end_date', '>=', start)])
        tasks = self.env['ops.task'].search([('task_def_id', 'in', definitions.ids),
                                           ('scheduled_date', '>=', start), ('scheduled_date', '<=', end)])
        result['plans'] = len(definitions)
        known = {(t.task_def_id.id, t.period_key) for t in tasks}
        for plan in definitions:
            if plan.periodicity == 'adhoc':
                continue  # Cannot infer real-world events from a missing record.
            day = max(start, plan.sq_start_date)
            stop = min(end, today, plan.sq_end_date or end)
            while day <= stop:
                key, _scheduled = plan._period_info(day)
                if key and (plan.id, key) not in known:
                    result['missing'] += 1
                day += timedelta(days=1)
        result['overdue'] = len(tasks.filtered(lambda t: t.due_date < today and t.state in ('todo', 'done')))
        result['ng'] = len(tasks.filtered(lambda t: t.sq_result == 'ng' and t.state != 'approved'))
        sheets = self.env['iatf.check.sheet'].browse(self._bound_source_ids('iatf.check.sheet')).exists()
        sheets.check_access('read')
        sheets.item_ids.check_access('read')
        result['sheet_overdue'] = len(sheets.filtered('active').item_ids.filtered(lambda i: i.active and i.is_overdue))
        result['status'] = ('관리계획 미설정' if not definitions else
                            '미실시·후속조치 확인 필요' if any(result[k] for k in ('missing', 'overdue', 'sheet_overdue', 'ng'))
                            else '조회 범위 내 누락 없음 · SQ 적합 판정 아님')
        return result

    @api.depends_context('uid', 'allowed_company_ids', 'sq_date_from', 'sq_date_to', 'tz')
    def _compute_daily(self):
        for item in self:
            try:
                data = item._daily_snapshot()
            except AccessError:
                data = dict(status='집계 미확인: 연결 원천 접근 제한', period='', plans=0, missing=0,
                            overdue=0, sheet_overdue=0, ng=0)
            item.daily_status = data['status']
            item.daily_period = data['period']
            item.daily_plan_count = data['plans']
            item.daily_missing_count = data['missing']
            item.daily_overdue_count = data['overdue']
            item.daily_sheet_overdue = data['sheet_overdue']
            item.daily_pending_ng = data['ng']

    def action_daily_plans(self):
        self.ensure_one()
        self.check_access('read')
        self.env['ops.task.def'].check_access('read')
        return {'type': 'ir.actions.act_window', 'name': self.code + ' 관리계획',
                'res_model': 'ops.task.def', 'view_mode': 'list,form',
                'domain': [('sq_item_id', '=', self.id)],
                'context': dict(self.env.context, default_sq_item_id=self.id, active_test=False)}

    def action_daily_tasks(self):
        self.ensure_one()
        self.check_access('read')
        self.env['ops.task'].check_access('read')
        start, end, _today = self._daily_window()
        return {'type': 'ir.actions.act_window', 'name': self.code + ' 수행 업무',
                'res_model': 'ops.task', 'view_mode': 'list,form',
                'domain': [('sq_item_id', '=', self.id), ('scheduled_date', '>=', start), ('scheduled_date', '<=', end)],
                'context': dict(self.env.context, create=False, delete=False)}


class SqDailyRole(models.Model):
    _inherit = 'ops.role'

    sq_approver_definition_ids = fields.One2many('ops.task.def', 'approver_role_id',
                                                string='SQ 조회용 승인 역할 업무', readonly=True)
