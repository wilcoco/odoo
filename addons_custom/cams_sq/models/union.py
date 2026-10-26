"""Source-versioned union catalog; never rewrite an assessed historical revision."""
import json
import re
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import file_open

REVISION = '2026-10-union'


class SqUnionStandard(models.Model):
    _inherit = 'sq.standard'
    scored_points = fields.Float('평가 대상 배점', compute='_compute_scored_points')
    import_note = fields.Text('적재 제외·해석 기록', readonly=True)

    @api.depends('item_ids.points', 'item_ids.internal_only')
    def _compute_scored_points(self):
        for standard in self:
            standard.scored_points = sum(standard.item_ids.filtered(lambda i: not i.internal_only).mapped('points'))

    @api.model
    def action_load_union(self):
        if not self.env.su and not self.env.user.has_group('cams_sq.group_sq_manager'):
            raise UserError(_('SQ 관리자만 합집합 기준을 적재할 수 있습니다.'))
        with self.env.cr.savepoint():
            self._load_union()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': '합집합 기준 적재', 'message': '사출 49·조립 36 / 도장 제외. 기존 개정·평가를 보존했습니다.', 'sticky': False}}

    def _load_union(self):
        with file_open('cams_sq/data/union_20261023.json', 'r') as source:
            data = json.load(source)
        company = self.env.company
        # Serialize repeat imports, including concurrent button presses.
        self.env.cr.execute('SELECT id FROM res_company WHERE id=%s FOR UPDATE', [company.id])
        standards, items = {}, {}
        for sector, count, points in [('INJ', 49, 1030), ('ASM', 36, 1000)]:
            standard = self.search([('company_id', '=', company.id), ('sector', '=', sector), ('revision', '=', REVISION)])
            if not standard:
                standard = self.create({'name': ('사출' if sector == 'INJ' else '전기조립') + ' 합집합 2026-10',
                    'company_id': company.id, 'sector': sector, 'revision': REVISION,
                    'source_commit': data['source_commit'],
                    'import_note': 'D-34: 사내 관리 2건은 원문 배점만 보존하고 평가 득점·분모에서 제외. '
                        '2026-10-23 사용자 정정 승인: INJ 원문 1030 / 평가 대상 1010. '
                        '도장 21항목·별칭 21·지적 21 제외. CREA-DOCLIST 5구간은 항목이 아님. '
                        'CREA-REVIEW 6-13·6-14는 대응 항목 부재로 연결 보류. 제외·보류 원문은 JSON에 보존.'})
            elif standard.source_commit != data['source_commit']:
                raise UserError(_('합집합 출처가 바뀌었습니다. 새 개정이 필요합니다.'))
            standards[sector] = standard
            rows = [r for r in data['union_items'] if r['industry'] == sector]
            for row in rows:
                internal = sector == 'INJ' and row['union_code'] in ('6_X1', '6_X2')
                area_code = 'INTERNAL' if internal else row['area_no']
                area = self.env['sq.area'].search([('standard_id', '=', standard.id), ('code', '=', area_code)])
                if not area:
                    area = self.env['sq.area'].create({'standard_id': standard.id, 'code': area_code,
                        'name': '사내 관리 (평가 점수 제외)' if internal else row['area_name']})
                code = sector + '.' + row['union_code']
                values = {'standard_id': standard.id, 'area_id': area.id, 'code': code,
                    'number': row['union_code'], 'name': row['name'], 'requirement': row['requirement'],
                    'points': float(re.match(r'\d+(?:\.\d+)?', row['points_union'])[0]),
                    'internal_only': internal, 'source': 'sq-union/union_items.csv@' + data['source_commit'],
                    'source_owner': '생산계획 + 품질' if code == 'INJ.1_4' else '',
                    'applicability_note': row['note']}
                item = self.env['sq.item'].search([('standard_id', '=', standard.id), ('code', '=', code)])
                if item:
                    for key in ('name', 'number', 'points', 'requirement', 'internal_only'):
                        if (item[key] or '') != (values[key] or ''):
                            raise UserError(_('합집합 원문과 다릅니다. 새 개정이 필요합니다: %s') % code)
                else:
                    item = self.env['sq.item'].create(values)
                items[code] = item
            if len(standard.item_ids) != count or standard.total_points != points:
                raise UserError(_('합집합 항목 수·원문 배점 검증 실패: %s') % sector)
        for row in data['item_alias']:
            if not row['union_code'] or row['source'] == 'CREA-PAINT-2026':
                continue
            sector = 'ASM' if row['source'] == 'SW-PREP-250912' else 'INJ'
            item = items.get(sector + '.' + row['union_code'])
            if not item and row['source'] == 'CREA-REVIEW' and row['union_code'] in ('6_13', '6_14'):
                continue  # Explicit unresolved mappings, retained in the source and import note.
            if not item:
                raise UserError(_('별칭 대응 항목이 없습니다: %s') % row['external_code'])
            alias = self.env['sq.item.alias'].search([('standard_id', '=', item.standard_id.id),
                ('revision', '=', row['source']), ('number', '=', row['external_code'])])
            if alias and alias.item_id != item:
                raise UserError(_('별칭 대응 충돌: %s') % row['external_code'])
            if not alias:
                self.env['sq.item.alias'].create({'item_id': item.id, 'revision': row['source'],
                    'number': row['external_code'], 'source': row['source'],
                    'external_code': row['external_code'], 'basis': row['basis']})
        # OURS-48 provides semantic translation (numbers shifted in areas 1 and 6).
        # Keep old links; add new revision links instead of moving historical evidence.
        mapping = {r['external_code']: r['union_code'] for r in data['item_alias'] if r['source'] == 'OURS-48'}
        for sector in ('INJ', 'ASM'):
            old = self.search([('company_id', '=', company.id), ('sector', '=', sector),
                              ('revision', '!=', REVISION)], order='id', limit=1)
            for previous in old.item_ids:
                number = mapping.get(previous.number) if sector == 'INJ' else previous.number
                current = items.get(sector + '.' + (number or ''))
                if not current:
                    continue
                for requirement in previous.requirement_ids:
                    if current not in requirement.item_ids:
                        requirement.write({'item_ids': [(4, current.id)]})
                for rule in previous.rule_ids.with_context(active_test=False):
                    if not self.env['sq.evidence.rule'].with_context(active_test=False).search_count([
                            ('item_id', '=', current.id), ('source_key', '=', rule.source_key)]):
                        rule.copy({'item_id': current.id})
                for binding in previous.binding_ids.with_context(active_test=False):
                    if not self.env['sq.evidence.binding'].with_context(active_test=False).search_count([
                            ('item_id', '=', current.id), ('source_ref', '=', '%s,%s' % (binding.source_ref._name, binding.source_ref.id))]):
                        binding.copy({'item_id': current.id})
        for row in data['external_findings']:
            if row['source'] == '크레아지적-도장':
                continue
            sector = 'ASM' if row['source'] == 'SW조립1차평가' else 'INJ'
            item = items.get(sector + '.' + row['union_code'])
            if not item:
                raise UserError(_('외부 지적 대응 항목이 없습니다: %s') % row['finding_id'])
            key = REVISION + ':' + row['finding_id']
            if not self.env['sq.external.finding'].search_count([('company_id', '=', company.id), ('source_key', '=', key)]):
                self.env['sq.external.finding'].create({'company_id': company.id, 'source_key': key,
                    'item_id': item.id, 'source': row['source'], 'evaluated_party': row['evaluated_party'],
                    'date': row['date'] or False, 'external_code': row['external_code'],
                    'rating': row['rating_or_score'], 'text': row['text'], 'improvement': row['improvement'],
                    'evidence': row['evidence_file']})
        for number, row in enumerate(data['standard_values'], 1):
            key = REVISION + ':VALUE-%02d' % number
            if not self.env['sq.standard.value'].search_count([('company_id', '=', company.id), ('source_key', '=', key)]):
                self.env['sq.standard.value'].create({'company_id': company.id, 'source_key': key,
                    'item_id': items['INJ.' + row['union_code']].id, 'union_code': 'INJ.' + row['union_code'],
                    'parameter': row['parameter'], 'value': row['escon_value'], 'source': row['escon_source'],
                    'reference_value': row['ref_value'], 'reference_source': row['ref_source'],
                    'unit': row['unit'], 'decision_needed': row['decision_needed'] == 'Y',
                    'decision': '참고 — 생산기술·품질 실제 값 확정 필요' if row['decision_needed'] == 'Y' else '에스콘 원문 기준'})
        return standards


class SqUnionItem(models.Model):
    _inherit = 'sq.item'
    internal_only = fields.Boolean('사내 관리 (점수 제외)', readonly=True)
    external_finding_ids = fields.One2many('sq.external.finding', 'item_id', string='외부 지적')

    def write(self, vals):
        if 'internal_only' in vals and self.env['sq.assessment.line'].search_count([('item_id', 'in', self.ids)]):
            raise UserError(_('평가에 사용한 항목의 채점 범위는 새 개정으로 변경하십시오.'))
        return super().write(vals)


class SqUnionAlias(models.Model):
    _inherit = 'sq.item.alias'
    # Existing source is Char and is deliberately preserved for older imports.
    external_code = fields.Char('외부 원본 번호')
    basis = fields.Char('대응 근거 (동일문구/키워드/추정)')


class SqExternalFinding(models.Model):
    _name = 'sq.external.finding'
    _description = 'SQ 외부 평가·지적 (참고 원문)'
    _inherit = ['mail.thread']
    _check_company_auto = True
    _rec_name = 'external_code'
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    source_key = fields.Char(required=True, readonly=True, index=True)
    item_id = fields.Many2one('sq.item', required=True, check_company=True, ondelete='restrict')
    source = fields.Char('출처', required=True)
    evaluated_party = fields.Char('원문 평가 대상')
    date = fields.Date('평가일')
    external_code = fields.Char('원본 지적 번호')
    rating = fields.Char('원문 평가')
    text = fields.Text('지적 원문', required=True)
    improvement = fields.Text('개선안 원문')
    status = fields.Selection([('open', '미조치'), ('progress', '조치중'), ('done', '완료')], default='open', required=True, tracking=True)
    action_ids = fields.One2many('iatf.corrective.action', 'sq_external_finding_id', string='기존 시정조치')
    evidence = fields.Char('원문 근거 파일')
    _sql_constraints = [('source_key_unique', 'unique(company_id,source_key)', '외부 지적 원본 키가 중복됩니다.')]

    def write(self, vals):
        if set(vals) - {'status', 'action_ids', 'message_follower_ids', 'activity_ids'}:
            raise UserError(_('적재한 외부 원문은 변경할 수 없습니다. 조치는 기존 시정조치에 기록하십시오.'))
        return super().write(vals)

    @api.constrains('status', 'action_ids')
    def _check_completion(self):
        for row in self.filtered(lambda r: r.status == 'done'):
            if not row.action_ids or any(action.state != 'closed' for action in row.action_ids):
                raise ValidationError(_('연결한 시정조치의 검증·종료 후 완료하십시오.'))


class SqFindingAction(models.Model):
    _inherit = 'iatf.corrective.action'
    sq_external_finding_id = fields.Many2one('sq.external.finding', check_company=True, ondelete='restrict')


class SqStandardValue(models.Model):
    _name = 'sq.standard.value'
    _description = 'SQ 기준값 원문·확정 대기'
    _check_company_auto = True
    _inherit = ['mail.thread']
    _rec_name = 'parameter'
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    source_key = fields.Char(required=True, readonly=True)
    item_id = fields.Many2one('sq.item', required=True, check_company=True, ondelete='restrict')
    union_code = fields.Char(readonly=True)
    parameter = fields.Char('기준 항목', required=True, readonly=True)
    value = fields.Char('에스콘 원문 값', readonly=True)
    source = fields.Char('에스콘 출처', readonly=True)
    reference_value = fields.Char('타사 참고값 (자동 판정에 사용하지 않음)', readonly=True)
    reference_source = fields.Char('참고 출처', readonly=True)
    unit = fields.Char('단위', readonly=True)
    decision_needed = fields.Boolean('담당 확정 필요', readonly=True)
    decision = fields.Char('적재 판정', readonly=True)
    _sql_constraints = [('source_key_unique', 'unique(company_id,source_key)', '기준값 원본 키가 중복됩니다.')]

    def write(self, vals):
        raise UserError(_('원문 기준값은 보존합니다. 실제 확정값은 해당 업무 기준의 새 개정에 기록하십시오.'))


class SqUnionAudit(models.Model):
    _inherit = 'iatf.audit'
    sq_external_finding_ids = fields.Many2many('sq.external.finding', compute='_compute_external_findings', string='외부 지적 참고')

    @api.depends('sq_standard_id.item_ids.external_finding_ids')
    def _compute_external_findings(self):
        for audit in self:
            audit.sq_external_finding_ids = audit.sq_standard_id.item_ids.external_finding_ids

    def action_sq_propose(self):
        result = super().action_sq_propose()
        from .assessment import _TOKEN
        for line in self.sq_line_ids:
            findings = line.item_id.external_finding_ids.sorted(lambda r: (r.evaluated_party != '에스콘', r.id))
            if findings:
                reason = '\n\n외부 지적 참고 (자사 이행 실적·합격 근거 아님):\n' + '\n'.join(
                    '%s / %s [%s]: %s' % (r.source, r.external_code, r.evaluated_party, r.text) for r in findings)
                line.with_context(_sq_init=_TOKEN).write({'proposed_reason': (line.proposed_reason or '') + reason})
        return result
