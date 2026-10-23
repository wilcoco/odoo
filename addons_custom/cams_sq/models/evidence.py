import json
import pytz
from datetime import datetime, time, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression
from odoo.tools import file_open


class SqEvidenceRule(models.Model):
    _name = 'sq.evidence.rule'
    _description = 'SQ 증빙 조회 규칙'
    _check_company_auto = True
    name = fields.Char('명칭', required=True)
    item_id = fields.Many2one('sq.item', string='SQ 항목', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='item_id.company_id', store=True)
    source_key = fields.Char(required=True)
    model_name = fields.Char('원천 모델')
    domain_json = fields.Text('조건 (JSON)', default='[]', required=True)
    date_field = fields.Char('기간 필드')
    company_path = fields.Char('회사 필드 경로')
    note = fields.Text('조회 범위·현장 확인사항')
    period_days = fields.Integer('기록 확인 주기 (일)', default=0)
    active = fields.Boolean(default=True)
    scope_mode = fields.Selection([('company', '회사 원천'), ('binding', '이 항목에 연결한 원천')],
                                  string='증빙 범위', required=True, default='company')
    period_mode = fields.Selection([('event', '기간 실적'), ('current', '현재 기준·연결 문서')],
                                   string='기간 해석', required=True, default='event')
    review_revision = fields.Char('증빙 정합성 개정', readonly=True)
    evidence_count = fields.Integer('증빙 후보 수', compute='_compute_evidence')
    latest_date = fields.Char('최근 기록일', compute='_compute_evidence')
    evidence_state = fields.Char('확인 상태', compute='_compute_evidence')
    proposal_enabled = fields.Boolean('검증한 제안 규칙 사용', default=False)
    proposal_source = fields.Char('임계값 검증 근거')
    minimum_count = fields.Integer('보완 제안 최소 건수', default=1)
    _sql_constraints = [('rule_key', 'unique(item_id,source_key)', '같은 항목의 규칙 키 중복입니다.')]

    def _target(self):
        self.ensure_one()
        self.check_access('read')
        if self.company_id not in self.env.companies:
            raise AccessError(_('현재 허용된 회사의 규칙만 조회할 수 있습니다.'))
        if not self.model_name or self.model_name not in self.env:
            raise UserError(_('원천 모델 미설치 또는 현장 확인 항목입니다.'))
        # Never sudo evidence: source ACLs and rules remain authoritative.
        target = self.env[self.model_name].with_context(allowed_company_ids=[self.company_id.id])
        target.check_access('read')
        if not self.company_path:
            raise UserError(_('회사 경계가 확정되지 않아 조회하지 않습니다.'))
        current = target
        for part in self.company_path.split('.'):
            field = current._fields.get(part)
            if not field or field.type != 'many2one':
                raise UserError(_('회사 필드 경로를 확인하십시오.'))
            current = self.env[field.comodel_name]
        if current._name != 'res.company':
            raise UserError(_('회사 경로는 res.company로 끝나야 합니다.'))
        try:
            domain = json.loads(self.domain_json)
            if not isinstance(domain, list):
                raise ValueError()
            domain = expression.AND([domain, [(self.company_path, '=', self.company_id.id)]])
            if target._name == 'iatf.inspection.criteria' and self.company_path == 'product_id.company_id':
                # Shared products are explicit global master data; supplier scope still applies.
                domain = expression.AND([json.loads(self.domain_json),
                    [('product_id.company_id', 'in', [False, self.company_id.id])],
                    ['|', ('supplier_id', '=', False), ('supplier_id.company_id', 'in', [False, self.company_id.id])]])
            shared_paths = {'injection.rawmaterial.material': 'product_id.company_id',
                            'injection.weight.change.history': 'product_tmpl_id.company_id'}
            if shared_paths.get(target._name) == self.company_path:
                domain = expression.AND([json.loads(self.domain_json),
                    [(self.company_path, 'in', [False, self.company_id.id])]])
            if target._name == 'iatf.audit':
                # A self-assessment must not become its own proof of an IATF audit.
                domain = expression.AND([domain, [('audit_type', '!=', 'sq'), ('state', '!=', 'cancelled')]])
        except (ValueError, TypeError):
            raise UserError(_('조건은 JSON 도메인 목록이어야 합니다.'))
        # A company-wide checklist count cannot establish any particular SQ item.
        if target._name in ('iatf.check.sheet', 'iatf.check.record'):
            sheet_ids = self.item_id._bound_source_ids('iatf.check.sheet')
            if not sheet_ids:
                raise UserError(_('이 SQ 항목에 점검 시트가 연결되지 않았습니다. 기준 > 항목에서 기존 시트를 연결하십시오.'))
            if target._name == 'iatf.check.record':
                domain = expression.AND([domain, [('sheet_id', 'in', sheet_ids), ('state', '=', 'done')]])
            else:
                domain = expression.AND([domain, [('id', 'in', sheet_ids)]])
        elif self.scope_mode == 'binding':
            ids = self.item_id._bound_source_ids(target._name)
            if not ids:
                raise UserError(_('이 SQ 항목에 기존 증빙 문서가 연결되지 않았습니다. 기준 > 항목 또는 서류·담당에서 연결하십시오.'))
            domain = expression.AND([domain, [('id', 'in', ids)]])
            if target._name == 'iatf.document':
                domain = expression.AND([domain, [('state', '=', 'approved')]])
        date_from, date_to = self.env.context.get('sq_date_from'), self.env.context.get('sq_date_to')
        if self.period_mode == 'event' and (date_from or date_to):
            date_field = target._fields.get(self.date_field)
            if not date_field or date_field.type not in ('date', 'datetime'):
                raise UserError(_('기간 조회를 위한 날짜 필드가 없습니다.'))
            if date_from:
                domain.append((self.date_field, '>=', self._period_boundary(date_from, date_field)))
            if date_to:
                domain.append((self.date_field, '<', self._period_boundary(date_to, date_field, next_day=True)))
        return target, domain

    def _period_boundary(self, value, date_field, next_day=False):
        """A selected calendar day follows the reader's timezone; storage is UTC."""
        day = fields.Date.to_date(value) + timedelta(days=int(next_day))
        if date_field.type == 'date':
            return fields.Date.to_string(day)
        zone = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        local_midnight = zone.localize(datetime.combine(day, time.min))
        return fields.Datetime.to_string(local_midnight.astimezone(pytz.UTC).replace(tzinfo=None))

    def _snapshot(self):
        self.ensure_one()
        try:
            target, domain = self._target()
            count = target.search_count(domain)
            field = target._fields.get(self.date_field)
            last = target.search(domain, order=f'{self.date_field} desc, id desc' if field and field.store else 'id desc', limit=1)
            latest = str(last[self.date_field] or '') if last and field else ''
            status = '증빙 후보 있음 (판정 필요)' if count else '모름 (0건)'
            if self.period_mode == 'current':
                status += ' · 현재 기준/문서 조회, 증빙 적용기간은 내용 확인'
            if self.period_mode == 'event' and self.period_days and latest:
                if fields.Date.to_date(latest[:10]) < fields.Date.context_today(self) - timedelta(days=self.period_days):
                    status = '주기 내 기록 미확인'
            return {'rule': self.id, 'model': self.model_name, 'domain': domain,
                    'count': count, 'latest': latest, 'status': status,
                    'period_mode': self.period_mode, 'scope_mode': self.scope_mode,
                    'date_from': self.env.context.get('sq_date_from'), 'date_to': self.env.context.get('sq_date_to')}
        except (AccessError, UserError, ValueError) as error:
            return {'rule': self.id, 'count': 0, 'latest': '', 'status': str(error), 'unavailable': True}

    @api.depends('item_id.binding_ids.source_ref', 'item_id.binding_ids.active',
                 'item_id.requirement_ids.document_ids', 'scope_mode', 'period_mode',
                 'domain_json', 'date_field', 'model_name', 'company_path', 'period_days')
    @api.depends_context('allowed_company_ids', 'uid', 'tz', 'sq_date_from', 'sq_date_to')
    def _compute_evidence(self):
        for rule in self:
            snapshot = rule._snapshot()
            rule.evidence_count = snapshot['count']
            rule.latest_date = snapshot['latest']
            rule.evidence_state = snapshot['status']

    @api.constrains('domain_json', 'minimum_count', 'period_days', 'proposal_enabled', 'proposal_source')
    def _check_rule(self):
        for rule in self:
            try:
                assert isinstance(json.loads(rule.domain_json), list)
            except (ValueError, TypeError, AssertionError):
                raise ValidationError(_('조회 조건은 JSON 목록이어야 합니다.'))
            if rule.minimum_count < 1 or rule.period_days < 0:
                raise ValidationError(_('건수는 1 이상, 주기는 0 이상이어야 합니다.'))
            if rule.proposal_enabled and not (rule.proposal_source or '').strip():
                raise ValidationError(_('제안 규칙의 실데이터 검증 근거를 기록하십시오.'))

    def action_open_source(self):
        self.ensure_one()
        target, domain = self._target()
        # List-only entry point. Source editing remains in the original application.
        return {'type': 'ir.actions.act_window', 'name': self.item_id.code + ' ' + self.name,
                'res_model': target._name, 'view_mode': 'list', 'domain': domain,
                'context': dict(self.env.context, create=False, edit=False, delete=False)}

    @api.model
    def _load_catalog_rules(self, items):
        with file_open('cams_sq/data/evidence.json', 'r') as f:
            rules = json.load(f)
        for row in rules:
            item = items.get(row['code'])
            existing = self.with_context(active_test=False).search([('item_id', '=', item.id), ('source_key', '=', row['key'])], limit=1) if item else self.browse()
            if not item or existing:
                continue
            model = self.env[row['model']] if row['model'] in self.env else None
            company_path = ''
            if model is not None:
                for path in ('company_id', 'mo_id.company_id', 'production_id.company_id', 'mold_id.company_id', 'equipment_id.company_id', 'audit_id.company_id', 'workcenter_id.company_id', 'lot_id.company_id', 'silo_id.company_id', 'employee_id.company_id', 'product_id.company_id', 'product_tmpl_id.company_id', 'silo_id.warehouse_id.company_id', 'wc_id.company_id'):
                    current, valid = model, True
                    for part in path.split('.'):
                        field = current._fields.get(part)
                        if not field or field.type != 'many2one':
                            valid = False
                            break
                        current = self.env[field.comodel_name]
                    if valid and current._name == 'res.company':
                        company_path = path
                        break
            date_field = row.get('date_field', '')
            if model is not None and (not date_field or date_field not in model._fields):
                date_field = 'create_date' if 'create_date' in model._fields else ''
            self.create({'item_id': item.id, 'source_key': row['key'], 'name': row.get('label') or (model._description if model is not None else row['name']),
                         'model_name': row['model'], 'date_field': date_field, 'company_path': company_path,
                         'domain_json': json.dumps(row.get('domain', [])), 'note': row['note'],
                         'active': row.get('active', True), 'scope_mode': row.get('scope_mode', 'company'),
                         'period_mode': row.get('period_mode', 'event'), 'review_revision': row.get('review_revision', '')})
        self._apply_review_catalog(items, rules)
        loaded = self.search([('item_id', 'in', [item.id for item in items.values()])])
        # Complete only missing bindings; never replace an administrator's custom domain.
        for rule in loaded.filtered(lambda r: not r.company_path):
            path = {'iatf.competence.matrix': 'employee_id.company_id',
                    'iatf.inspection.criteria': 'product_id.company_id',
                    'injection.rawmaterial.material': 'product_id.company_id',
                    'injection.weight.change.history': 'product_tmpl_id.company_id',
                    'injection.silo.plc.reading': 'silo_id.warehouse_id.company_id',
                    'escon.wc.session': 'wc_id.company_id'}.get(rule.model_name)
            if path:
                rule.company_path = path
        for rule in loaded.filtered(lambda r: r.model_name in self.env):
            if rule.date_field not in self.env[rule.model_name]._fields:
                date_field = {'injection.weight.change.history': 'changed_at',
                              'injection.silo.plc.reading': 'plc_measured_at',
                              'escon.wc.session': 'started_at'}.get(rule.model_name)
                if date_field:
                    rule.date_field = date_field
        loaded._configure_metric_defaults()

    @api.model
    def _apply_review_catalog(self, items, rows):
        """Upgrade only audited stock bindings. Preserve administrator-specific rules."""
        with file_open('cams_sq/data/evidence_before_review.json', 'r') as stream:
            baseline = {(row['code'], row['key']): row for row in json.load(stream)}
        for row in rows:
            old = baseline.get((row['code'], row['key']))
            item = items.get(row['code'])
            if not old or not item:
                continue
            rule = self.with_context(active_test=False).search([('item_id', '=', item.id), ('source_key', '=', row['key'])], limit=1)
            if not rule or rule.review_revision:
                continue
            if rule.model_name != old['model'] or json.loads(rule.domain_json) != old.get('domain', []):
                continue
            # Source replacements use new keys and retire the old rule. Never repoint history.
            vals = {'review_revision': '20261021'}
            if not row.get('active', True):
                vals.update(active=False, proposal_enabled=False)
            # Explicit custom dates and metric settings survive a catalog reload.
            if rule.date_field in (old.get('date_field'), 'create_date', False):
                vals.update(date_field=row.get('date_field', rule.date_field),
                            period_mode=row.get('period_mode', 'event'))
            if row.get('scope_mode'):
                vals['scope_mode'] = row['scope_mode']
            if rule.note == old['note']:
                vals['note'] = row['note']
            rule.write(vals)
