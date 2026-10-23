from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression


class TaskDefinition(models.Model):
    _inherit = 'ops.task.def'
    # No default/backfill: existing shared definitions keep their historical scope.
    company_id = fields.Many2one('res.company', string='SQ 증빙 회사', tracking=True)
    sq_coverage_kind = fields.Selection([('weekend', '주말 점검'), ('overtime', '특근 점검')],
        string='품질관리 취약시간대', tracking=True)

    @api.constrains('company_id', 'sq_coverage_kind')
    def _check_sq_company(self):
        for task in self:
            if task.sq_coverage_kind and not task.company_id:
                raise ValidationError(_('취약시간대 점검에는 실제 담당 회사를 지정하십시오.'))
            if task.company_id and task.company_id not in self.env.companies:
                raise AccessError(_('허용된 회사만 지정할 수 있습니다.'))

    def write(self, values):
        keys = {'company_id', 'sq_coverage_kind'} & values.keys()
        for definition in self:
            changed = any((definition[key].id if key == 'company_id' else definition[key]) != values[key] for key in keys)
            if changed and definition.task_ids.filtered(lambda task: task.state in ('done', 'approved')):
                raise UserError(_('완료된 업무의 회사/취약시간대 분류는 바꿀 수 없습니다. 새 업무 정의를 만드십시오.'))
        return super().write(values)


class Binding(models.Model):
    _inherit = 'sq.evidence.binding'

    @api.model
    def _source_models(self):
        return super()._source_models() + [('ops.task.def', '기존 운영 업무 정의')]


class Rule(models.Model):
    _inherit = 'sq.evidence.rule'

    def _target(self):
        target, domain = super()._target()
        if self.source_key != 'union-INJ.1_4-coverage':
            return target, domain
        if target._name != 'ops.task' or self.company_path != 'task_def_id.company_id':
            raise UserError(_('취약시간대 규칙의 실제 원천·회사 경로를 확인하십시오.'))
        ids = self.item_id._bound_source_ids('ops.task.def')
        if not ids:
            raise UserError(_('INJ.1_4에 실제 주말·특근 업무 정의를 연결하십시오.'))
        start, end = self.env.context.get('sq_date_from'), self.env.context.get('sq_date_to')
        if not start or not end:
            raise UserError(_('취약시간대 점검의 확인 기간을 지정하십시오.'))
        start, end = fields.Date.to_date(start), fields.Date.to_date(end)
        if end < start or (end - start).days > 366:
            raise UserError(_('확인 기간은 1년 이내로 지정하십시오.'))
        weekends = []
        day = start
        while day <= end:
            if day.weekday() >= 5: weekends.append(day)
            day += timedelta(days=1)
        scope = expression.OR([
            [('task_def_id.sq_coverage_kind', '=', 'weekend'), ('scheduled_date', 'in', weekends)],
            [('task_def_id.sq_coverage_kind', '=', 'overtime'), ('scheduled_date', '>=', start), ('scheduled_date', '<=', end)]])
        completed = expression.OR([
            [('requires_approval', '=', False), ('state', 'in', ['done', 'approved'])],
            [('requires_approval', '=', True), ('state', '=', 'approved'), ('approve_uid', '!=', False), ('approve_date', '!=', False)]])
        return target, expression.AND([domain, scope, completed, [('task_def_id', 'in', ids),
            ('done_uid', '!=', False), ('done_date', '!=', False), ('done_note', '!=', False)]])


class Requirement(models.Model):
    _inherit = 'sq.doc.requirement'

    def _load_outputs(self):
        result = super()._load_outputs()
        item = self.env['sq.item'].search([('company_id', '=', self.env.company.id),
            ('code', '=', 'INJ.1_4'), ('standard_id.revision', '=', '2026-10-union')])
        if len(item) != 1:
            raise UserError(_('사출 합집합의 취약시간대 항목을 먼저 확인하십시오.'))
        Rule = self.env['sq.evidence.rule'].with_context(active_test=False)
        if not Rule.search_count([('item_id', '=', item.id), ('source_key', '=', 'union-INJ.1_4-coverage')]):
            Rule.create({'item_id': item.id, 'source_key': 'union-INJ.1_4-coverage',
                'name': '주말·특근 점검 완료/승인 근거', 'model_name': 'ops.task',
                'company_path': 'task_def_id.company_id', 'date_field': 'done_date',
                'domain_json': '[]', 'period_mode': 'event', 'scope_mode': 'company',
                'proposal_enabled': False, 'proposal_source': False,
                'note': '실제 회사·주말/특근 업무 정의를 항목에 연결한 뒤 조회. 최소1은 모델 기본값이며 확인된 평가 기준이 아님. D-24/D-38 및 실제 기대 건수 확정 전 제안 OFF.'})
        return result
