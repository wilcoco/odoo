"""SQ evidence on the existing operating ledger; unrelated Ops behavior is preserved."""
import json
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from .snapshot import _documents_snapshot, _checks_snapshot
from odoo.tools import html2plaintext

def _has_text(value):
    return bool(html2plaintext(value or "").strip())

_TOKEN = object()
_CTX = '_cams_sq_ops'
_PROTECTED = {'state', 'done_uid', 'done_date', 'approve_uid', 'approve_date',
              'sq_execution_snapshot', 'sq_company_id', 'sq_item_id'}
_EVIDENCE = {'sq_performed_date', 'sq_result', 'sq_document_ids', 'sq_finding_id', 'done_note',
             'sq_check_ids', 'sq_recheck_ids', 'sq_nonconformity_id'}
_IDENTITY = {'task_def_id', 'period_key', 'scheduled_date', 'due_date'}


def _internal(records):
    return records.with_context(**{_CTX: _TOKEN})


class SqOpsDefinition(models.Model):
    _inherit = 'ops.task.def'

    sq_item_id = fields.Many2one('sq.item', string='SQ 관리 항목', ondelete='restrict', index=True)
    sq_start_date = fields.Date('SQ 관리 시작일', default=lambda self: fields.Date.context_today(self))
    sq_end_date = fields.Date('SQ 관리 종료일')
    sq_company_id = fields.Many2one(related='sq_item_id.company_id', store=True, index=True)
    sq_sheet_ids = fields.Many2many('iatf.check.sheet', 'sq_plan_sheet_rel', 'plan_id', 'sheet_id',
                                   string='필수 점검 시트')
    sq_shift = fields.Selection([('day', '주간'), ('evening', '야간'), ('night', '심야')],
                                string='대상 근무조', help='교대 점검은 근무조마다 별도 관리계획으로 지정합니다.')
    sq_required_document_ids = fields.Many2many('iatf.document', 'sq_plan_document_rel', 'plan_id', 'document_id',
        string='필수 확인 문서', help='같은 SQ 항목에 연결한 관리대장·마스터·기준 문서입니다. 실제 수행 기록도 별도로 확인하십시오.')

    @api.constrains('sq_item_id', 'sq_required_document_ids')
    def _check_sq_documents(self):
        for plan in self.filtered('sq_required_document_ids'):
            if not plan.sq_item_id:
                raise UserError(_('필수 확인 문서는 SQ 항목을 지정한 뒤 연결하십시오.'))
            documents = plan.sq_required_document_ids
            documents.check_access('read')
            bound = plan.sq_item_id._bound_source_ids('iatf.document')
            if any(d.id not in bound or d.company_id != plan.sq_company_id for d in documents):
                raise UserError(_('같은 SQ 항목에 명시적으로 연결한 같은 회사 문서만 필수 확인 대상으로 지정하십시오.'))

    @api.constrains('sq_item_id', 'sq_sheet_ids', 'sq_shift')
    def _check_sq_sheets(self):
        for plan in self.filtered('sq_sheet_ids'):
            if not plan.sq_item_id:
                raise UserError(_('필수 점검 시트는 SQ 관리 항목을 지정한 뒤 연결하십시오.'))
            bound = plan.sq_item_id._bound_source_ids('iatf.check.sheet')
            plan.sq_sheet_ids.check_access('read')
            if any(s.id not in bound or s.company_id != plan.sq_company_id or not s.active
                   for s in plan.sq_sheet_ids):
                raise UserError(_('해당 SQ 항목에 명시적으로 연결된 같은 회사의 사용 중인 시트만 지정하십시오.'))
            if not plan.sq_shift and any(s.cycle == 'shift' or any(i.cycle == 'shift' for i in s.item_ids)
                                        for s in plan.sq_sheet_ids):
                raise UserError(_('교대 점검은 대상 근무조를 지정하고 근무조마다 관리계획을 만드십시오.'))

    @api.constrains('sq_item_id', 'requires_approval', 'due_days', 'sq_start_date', 'sq_end_date')
    def _check_sq_definition(self):
        for record in self.filtered('sq_item_id'):
            record.sq_item_id.check_access('read')
            if record.sq_company_id not in self.env.companies:
                raise AccessError(_('현재 허용된 회사의 SQ 항목만 연결하십시오.'))
            if not record.sq_start_date or (record.sq_end_date and record.sq_end_date < record.sq_start_date):
                raise UserError(_('SQ 관리 시작일·종료일을 확인하십시오.'))
            if not record.requires_approval or record.due_days < 0:
                raise UserError(_('SQ 관리 업무는 독립 승인과 0일 이상의 기한이 필요합니다.'))

    def write(self, vals):
        if 'sq_company_id' in vals:
            raise UserError(_('SQ 회사는 연결한 항목으로 결정됩니다.'))
        if 'sq_item_id' in vals and any(r.task_ids for r in self):
            raise UserError(_('업무 이력이 있는 관리계획은 SQ 연결을 바꿀 수 없습니다. 새 계획을 만드십시오.'))
        schedule = {'sq_start_date', 'periodicity', 'weekday', 'day_of_month', 'due_days', 'sq_sheet_ids', 'sq_shift', 'sq_required_document_ids'}
        if schedule & vals.keys() and any(r.sq_item_id and r.task_ids for r in self):
            raise UserError(_('SQ 이력이 있는 주기는 종료일을 정하고 새 관리계획으로 변경하십시오.'))
        if vals.get('sq_end_date') and fields.Date.to_date(vals['sq_end_date']) < fields.Date.context_today(self):
            if self.filtered('sq_item_id'):
                raise UserError(_('SQ 종료일을 과거로 소급하여 누락 업무를 제거할 수 없습니다.'))
        if vals.get('active') is False and any(r.sq_item_id and not (vals.get('sq_end_date') or r.sq_end_date) for r in self):
            raise UserError(_('SQ 관리 종료일을 지정한 뒤 보관하십시오.'))
        return super().write(vals)

    def _create_task(self, period_key, scheduled):
        self.ensure_one()
        if self.sq_item_id and (scheduled < self.sq_start_date or (self.sq_end_date and scheduled > self.sq_end_date)):
            return self.env['ops.task']
        if self.sq_item_id and self.periodicity != 'adhoc':
            # Resolve the canonical scheduled day of this period; a late manual
            # generation must not move its deadline forward and conceal delay.
            candidate = scheduled
            for _day in range(367):
                expected, _scheduled = self._period_info(candidate)
                if expected == period_key:
                    scheduled = candidate
                    break
                candidate -= timedelta(days=1)
            else:
                raise UserError(_('SQ 정기 업무의 예정 주기와 기간 키가 일치하지 않습니다.'))
            if scheduled < self.sq_start_date or (self.sq_end_date and scheduled > self.sq_end_date):
                return self.env['ops.task']
        task = super(SqOpsDefinition, _internal(self))._create_task(period_key, scheduled)
        return task.with_env(self.env)

    def unlink(self):
        if any(r.sq_item_id and r.task_ids for r in self):
            raise UserError(_('SQ 운영 이력은 삭제하지 말고 관리계획을 보관하십시오.'))
        return super().unlink()


class SqOpsTask(models.Model):
    _inherit = 'ops.task'

    sq_item_id = fields.Many2one(related='task_def_id.sq_item_id', store=True, index=True)
    sq_company_id = fields.Many2one(related='sq_item_id.company_id', store=True, index=True)
    sq_performed_date = fields.Date('실제 수행일', tracking=True)
    sq_result = fields.Selection([('ok', '정상'), ('ng', '이상 발견')], string='SQ 수행 결과', tracking=True)
    sq_document_ids = fields.Many2many('iatf.document', 'cams_sq_ops_document_rel', 'task_id', 'document_id',
                                      string='실제 수행 증빙 문서')
    sq_finding_id = fields.Many2one('iatf.audit.finding', string='이상 조치 지적', ondelete='restrict')
    sq_execution_snapshot = fields.Json('승인 대조용 수행 근거', readonly=True, copy=False)
    sq_check_ids = fields.Many2many('iatf.check.record', 'sq_task_check_rel', 'task_id', 'record_id',
                                   string='실제 완료 점검표')
    sq_recheck_ids = fields.Many2many('iatf.check.record', 'sq_task_recheck_rel', 'task_id', 'record_id',
                                     string='조치 후 재점검표')
    sq_nonconformity_id = fields.Many2one('iatf.nonconformity', string='기존 부적합·시정조치', ondelete='restrict')

    @api.constrains('sq_item_id', 'sq_check_ids', 'sq_recheck_ids', 'sq_nonconformity_id')
    def _check_direct_sources(self):
        for task in self:
            sources = task.sq_check_ids | task.sq_recheck_ids
            if not (sources or task.sq_nonconformity_id):
                continue
            if not task.sq_item_id:
                raise UserError(_('SQ 증빙은 SQ 관리계획의 업무에만 연결하십시오.'))
            sources.check_access('read')
            if task.sq_nonconformity_id:
                task.sq_nonconformity_id.check_access('read')
            if (any(r.company_id != task.sq_company_id or r.sheet_id.company_id != task.sq_company_id
                    for r in sources) or
                    (task.sq_nonconformity_id and task.sq_nonconformity_id.company_id != task.sq_company_id)):
                raise UserError(_('같은 회사의 점검표와 부적합만 연결하십시오.'))
            if task.sq_check_ids & task.sq_recheck_ids:
                raise UserError(_('원래 점검과 재점검은 서로 다른 완료 기록이어야 합니다.'))

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['task_def_id'] + list(_PROTECTED))
        prepared = []
        for vals in vals_list:
            if any(vals.get(k, defaults.get(k)) for k in ('sq_item_id', 'sq_company_id')):
                raise UserError(_('SQ 소속은 관리계획으로 지정하십시오.'))
            definition = self.env['ops.task.def'].browse(vals.get('task_def_id', defaults.get('task_def_id')))
            definition.check_access('read')
            if definition.sq_item_id:
                if self.env.context.get(_CTX) is not _TOKEN:
                    raise UserError(_('SQ 수행 업무는 관리계획의 현재 기간 업무 생성 버튼으로 생성하십시오.'))
                vals = dict(vals, state='todo', done_uid=False, done_date=False, approve_uid=False,
                            approve_date=False, sq_execution_snapshot=False)
                vals.pop('sq_item_id', None)
                vals.pop('sq_company_id', None)
            prepared.append(vals)
        return super().create(prepared)

    @api.constrains('sq_item_id', 'scheduled_date', 'due_date', 'sq_document_ids', 'sq_finding_id')
    def _check_sq_links(self):
        for task in self.filtered('sq_item_id'):
            task.sq_item_id.check_access('read')
            if task.sq_company_id not in self.env.companies:
                raise AccessError(_('현재 허용된 회사의 SQ 업무만 처리하십시오.'))
            if not task.due_date or task.due_date < task.scheduled_date:
                raise UserError(_('SQ 업무에는 예정일 이후의 기한이 필요합니다.'))
            if any(d.company_id != task.sq_company_id for d in task.sq_document_ids):
                raise UserError(_('같은 회사의 SQ 수행 문서만 연결하십시오.'))
            if task.sq_finding_id and task.sq_finding_id.audit_id.sq_standard_id != task.sq_item_id.standard_id:
                raise UserError(_('같은 SQ 평가대상의 지적만 연결하십시오.'))

    def _sq_lock(self):
        self.check_access('write')
        if self:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM ops_task WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(self.ids)])
            self.invalidate_recordset()

    def _sq_snapshot(self, lock=True):
        self.ensure_one()
        if (not self.sq_performed_date or self.sq_performed_date > fields.Date.context_today(self)
                or self.sq_performed_date < self.scheduled_date or not self.sq_result
                or not _has_text(self.done_note) or not (self.sq_document_ids or self.sq_check_ids)):
            raise UserError(_('예정일 이후 실제 수행일·결과·수행 내용과 승인 문서 또는 완료 점검표를 연결하십시오.'))
        if self.sq_result == 'ng' and not (self.sq_finding_id or self.sq_nonconformity_id):
            raise UserError(_('이상 발견 업무에는 기존 지적 또는 부적합·시정조치를 연결하십시오.'))
        finding = self.sq_finding_id
        if finding:
            finding.check_access('read')
        standard = self.sq_item_id.standard_id
        snapshot = {'item': self.sq_item_id.id, 'standard': standard.id, 'company': self.sq_company_id.id,
                'scope': [standard.sector, standard.revision],
                'scheduled': str(self.scheduled_date), 'due': str(self.due_date),
                'performed': str(self.sq_performed_date), 'result': self.sq_result,
                'note': self.done_note, 'finding': finding.id,
                'documents': _documents_snapshot(self.sq_document_ids, self.sq_company_id, lock=lock)}
        required = self.task_def_id.sq_sheet_ids
        self.task_def_id._check_sq_documents()
        if self.task_def_id.sq_required_document_ids - self.sq_document_ids:
            raise UserError(_('관리계획의 필수 확인 문서를 모두 연결하고 승인본을 확인하십시오.'))
        if required or self.sq_check_ids or self.sq_recheck_ids:
            checks = _checks_snapshot(self, self.sq_check_ids, lock=lock)
            rechecks = _checks_snapshot(self, self.sq_recheck_ids, lock=lock)
            if set(required.ids) - {r['sheet'] for r in checks}:
                raise UserError(_('관리계획의 모든 필수 시트에 대해 실제 완료 점검표를 연결하십시오.'))
            if any(r['result'] == 'issue' for r in checks):
                if self.sq_result != 'ng' or not self.sq_nonconformity_id:
                    raise UserError(_('NG 점검표는 이상 발견으로 보고하고 기존 부적합에 연결하십시오.'))
            if any(r['result'] != 'ok' for r in rechecks):
                raise UserError(_('재점검은 실제 양호로 완료한 기록만 연결하십시오.'))
            snapshot.update(checks=checks, rechecks=rechecks)
        if self.sq_nonconformity_id:
            nc = self.sq_nonconformity_id
            nc.check_access('read')
            if nc.company_id != self.sq_company_id or nc.state == 'cancelled':
                raise UserError(_('같은 회사의 취소되지 않은 부적합을 연결하십시오.'))
            snapshot['nonconformity'] = nc.id
        return snapshot

    def _sq_check_closed_loop(self):
        """Closing the follow-up never changes the original NG measurement."""
        self.ensure_one()
        nc = self.sq_nonconformity_id
        if nc:
            nc.check_access('read')
            nc.flush_recordset()
            self.env.cr.execute('SELECT id FROM iatf_nonconformity WHERE id=%s FOR UPDATE', [nc.id])
            nc.invalidate_recordset()
            if nc.state != 'closed':
                raise UserError(_('연결한 부적합의 조치·검증 종료 후 업무를 승인하십시오.'))
            actions = nc.corrective_action_ids
            actions.check_access('read')
            if actions:
                actions.flush_recordset()
                self.env.cr.execute('SELECT id FROM iatf_corrective_action WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(actions.ids)])
                actions.invalidate_recordset()
            if not actions or any(a.state not in ('verified', 'closed') or a.effective != 'yes'
                                  or not _has_text(a.verification_result) for a in actions):
                raise UserError(_('부적합에 유효성이 검증된 시정조치와 검증 결과를 남기십시오.'))
        for record in self.sq_check_ids.filtered(lambda r: r._derive_overall()[0] == 'issue'):
            latest = record.snapshot_ids.sorted('revision')[-1:]
            candidates = self.sq_recheck_ids.filtered(lambda r: r.sheet_id == record.sheet_id
                and r.check_date >= record.check_date and r.state == 'done' and r._derive_overall()[0] == 'ok')
            failed = {(l.item_id.id or l.item_name) for l in record.line_ids if l.result == 'ng'}
            if not any(latest and r.snapshot_ids and
                       (r.snapshot_ids.sorted('revision')[-1].done_at, r.snapshot_ids.sorted('revision')[-1].id)
                       > (latest.done_at, latest.id) and r.id != record.id and
                       failed <= {(l.item_id.id or l.item_name) for l in r.line_ids if l.result == 'ok'}
                       for r in candidates):
                raise UserError(_('각 NG 시트의 불량 항목을 조치 후 다시 측정한 양호 완료 점검표가 필요합니다.'))

    def write(self, vals):
        sq = self.filtered('sq_item_id')
        if 'task_def_id' in vals:
            target = self.env['ops.task.def'].browse(vals['task_def_id'])
            target.check_access('read')
            if sq or target.sq_item_id:
                raise UserError(_('기존 업무를 SQ 항목으로 옮길 수 없습니다. 관리계획에서 새 업무를 만드십시오.'))
        if sq and self.env.context.get(_CTX) is not _TOKEN:
            sq._sq_lock()
            if (_PROTECTED | _IDENTITY) & vals.keys():
                raise UserError(_('SQ 상태·승인이력·예정일·기한은 직접 변경할 수 없습니다. 업무 버튼을 사용하십시오.'))
            if _EVIDENCE & vals.keys() and any(t.state != 'todo' for t in sq):
                raise UserError(_('SQ 완료 보고를 재작업으로 회수한 뒤 증빙을 수정하십시오.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('sq_item_id'):
            raise UserError(_('SQ 수행 이력은 삭제할 수 없습니다. 미실시 사유를 남기십시오.'))
        return super().unlink()

    def action_mark_done(self):
        with self.env.cr.savepoint():
            sq = self.filtered('sq_item_id')
            sq._sq_lock()
            for task in sq:
                snapshot = task._sq_snapshot()
                _internal(task).write({'sq_execution_snapshot': snapshot})
            return super(SqOpsTask, _internal(self)).action_mark_done()

    def action_approve(self):
        with self.env.cr.savepoint():
            sq = self.filtered('sq_item_id')
            sq._sq_lock()
            for task in sq:
                if task.done_uid == self.env.user:
                    raise AccessError(_('SQ 수행자와 다른 승인자가 확인하십시오.'))
                if not task.sq_execution_snapshot or task.sq_execution_snapshot != task._sq_snapshot():
                    raise UserError(_('수행 근거가 변경되었습니다. 재작업 후 다시 보고하십시오.'))
                task._sq_check_closed_loop()
            return super(SqOpsTask, _internal(self)).action_approve()

    def _sq_allow_recall(self):
        self._sq_lock()
        for task in self:
            if not task._can_approve(self.env.user):
                raise AccessError(_('SQ 업무 회수·미실시 처리는 승인 역할 또는 운영관리자가 수행하십시오.'))
            task.message_post(body=_('SQ 이전 상태·수행 근거 보존: %s') % json.dumps({
                'state': task.state, 'done_uid': task.done_uid.id, 'approve_uid': task.approve_uid.id,
                'evidence': task.sq_execution_snapshot}, ensure_ascii=False))

    def action_reset_todo(self):
        with self.env.cr.savepoint():
            sq = self.filtered('sq_item_id')
            sq._sq_allow_recall()
            _internal(sq).write({'sq_execution_snapshot': False})
            return super(SqOpsTask, _internal(self)).action_reset_todo()

    def action_skip(self):
        with self.env.cr.savepoint():
            sq = self.filtered('sq_item_id')
            sq._sq_allow_recall()
            if any(not _has_text(t.done_note) for t in sq):
                raise UserError(_('미실시 사유를 수행 메모에 남기십시오.'))
            return super(SqOpsTask, _internal(self)).action_skip()
