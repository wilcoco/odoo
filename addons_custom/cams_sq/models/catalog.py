import json
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import file_open


class SqStandard(models.Model):
    _name = 'sq.standard'
    _description = 'SQ 평가 기준'
    _inherit = ['mail.thread']
    _check_company_auto = True

    name = fields.Char('명칭', required=True)
    sector = fields.Selection([('INJ', '사출'), ('ASM', '전기조립')], string='업종', required=True, readonly=True)
    revision = fields.Char('기준 개정', required=True, readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    good_ratio = fields.Float('양호 비율', default=1.0, tracking=True)
    partial_ratio = fields.Float('보완 비율', default=0.6, tracking=True)
    poor_ratio = fields.Float('미흡 비율', default=0.0, tracking=True)
    ratio_source = fields.Char('비율 출처', required=True, tracking=True,
        default='관례값(HKMC 기준서 미확인, 2026-10-19 대표 결정)')
    source_commit = fields.Char('기준 출처 버전', readonly=True)
    item_ids = fields.One2many('sq.item', 'standard_id', string='평가 항목')
    area_ids = fields.One2many('sq.area', 'standard_id', string='영역')
    total_points = fields.Float('총 배점', compute='_compute_total')
    _sql_constraints = [('standard_key', 'unique(company_id, sector, revision)', '회사·업종·개정은 중복할 수 없습니다.')]

    @api.depends('item_ids.points')
    def _compute_total(self):
        for record in self:
            record.total_points = sum(record.item_ids.mapped('points'))

    @api.constrains('good_ratio', 'partial_ratio', 'poor_ratio')
    def _check_ratios(self):
        for record in self:
            if not 0 <= record.poor_ratio <= record.partial_ratio <= record.good_ratio <= 1:
                raise ValidationError(_('채점 비율은 0~1이며 미흡 ≤ 보완 ≤ 양호여야 합니다.'))

    def write(self, vals):
        if {'sector', 'revision', 'company_id'} & vals.keys():
            raise UserError(_('기준의 회사·업종·개정 키는 변경할 수 없습니다. 새 개정을 등록하십시오.'))
        return super().write(vals)

    @api.model
    def action_load_catalog(self):
        if not self.env.su and not self.env.user.has_group('cams_sq.group_sq_manager'):
            raise UserError(_('SQ 관리자만 기준을 적재할 수 있습니다.'))
        with file_open('cams_sq/data/catalog.json', 'r') as f:
            data = json.load(f)
        company = self.env.company
        items = {}
        for source in data['standards']:
            standard = self.search([('company_id', '=', company.id), ('sector', '=', source['sector']),
                                    ('revision', '=', source['revision'])], limit=1)
            if not standard:
                standard = self.create({'company_id': company.id, 'sector': source['sector'],
                    'revision': source['revision'], 'source_commit': data['source_commit'],
                    'name': ('사출' if source['sector'] == 'INJ' else '전기조립') + ' SQ ' + source['revision']})
            for source_item in source['items']:
                area_code = source_item['number'].split('_')[0]
                area = self.env['sq.area'].search([('standard_id', '=', standard.id), ('code', '=', area_code)], limit=1)
                if not area:
                    area = self.env['sq.area'].create({'standard_id': standard.id, 'code': area_code,
                                                      'name': source_item['area']})
                item = self.env['sq.item'].search([('standard_id', '=', standard.id), ('code', '=', source_item['code'])], limit=1)
                values = {'name': source_item['name'], 'number': source_item['number'],
                          'points': source_item['points'], 'requirement': source_item['text'],
                          'source': source_item['source'], 'area_id': area.id,
                          'source_owner': source_item.get('source_owner', ''),
                          'applicability_note': source_item.get('applicability_note', '')}
                if item:
                    # A changed source requires a NEW standard revision, never edit an assessed baseline.
                    if any(item[k] != values[k] for k in ('name', 'number', 'points', 'requirement', 'source')):
                        raise UserError(_('기존 기준과 원본이 다릅니다. 새 개정으로 적재하십시오: %s') % item.code)
                else:
                    item = self.env['sq.item'].create(dict(values, code=source_item['code'], standard_id=standard.id))
                items[item.code] = item
                if not self.env['sq.item.alias'].search_count([('item_id', '=', item.id), ('revision', '=', source['revision']), ('number', '=', item.number)]):
                    self.env['sq.item.alias'].create({'item_id': item.id, 'revision': source['revision'], 'number': item.number})
            if standard.total_points != 1000:
                raise UserError(_('업종별 기준 배점 합계가 1000이 아닙니다.'))
        for alias in data.get('aliases', []):
            item = items[alias['code']]
            if not self.env['sq.item.alias'].search_count([('item_id','=',item.id),('revision','=',alias['revision']),('number','=',alias['number'])]):
                self.env['sq.item.alias'].create({'item_id':item.id,'revision':alias['revision'],'number':alias['number'],'source':alias['source']})
        for source in data['requirements'] + data['purchases']:
            record = self.env['sq.doc.requirement'].search([('company_id', '=', company.id), ('source_key', '=', source['key'])], limit=1)
            if not record:
                self.env['sq.doc.requirement'].create({'company_id': company.id, 'source_key': source['key'],
                    'name': source['name'], 'source': source['source'], 'source_owner': source.get('source_owner', ''),
                    'source_status': source.get('source_status', ''), 'source_quantity': source.get('source_quantity', ''),
                    'kind': 'purchase' if source['key'].startswith('PURCHASE') else 'document',
                    'item_ids': [(6, 0, [items[c].id for c in source.get('codes', [])])]})
        self.env['sq.evidence.rule']._load_catalog_rules(items)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'SQ 기준 적재', 'message': '사출 48·전기조립 36 / 서류 455·구매 12. 기존 준비·평가 결과는 유지됩니다.', 'sticky': False}}

    def action_new_assessment(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'iatf.audit', 'view_mode': 'form',
                'context': {'default_audit_type': 'sq', 'default_sq_standard_id': self.id,
                            'default_company_id': self.company_id.id, 'default_lead_auditor_id': self.env.uid}}


class SqArea(models.Model):
    _name = 'sq.area'
    _description = 'SQ 평가 영역'
    _order = 'standard_id, code'
    name = fields.Char('명칭', required=True)
    code = fields.Char(required=True)
    standard_id = fields.Many2one('sq.standard', string='SQ 기준', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='standard_id.company_id', store=True)
    item_ids = fields.One2many('sq.item', 'area_id')
    points = fields.Float('영역 배점', compute='_compute_points')
    _sql_constraints = [('area_key', 'unique(standard_id, code)', '영역 코드 중복입니다.')]

    @api.depends('item_ids.points')
    def _compute_points(self):
        for record in self:
            record.points = sum(record.item_ids.mapped('points'))


class SqItem(models.Model):
    _name = 'sq.item'
    _description = 'SQ 평가 항목'
    _order = 'standard_id, id'
    _check_company_auto = True
    name = fields.Char('명칭', required=True)
    code = fields.Char('안정 코드', required=True, readonly=True, index=True)
    number = fields.Char('표시 번호', required=True)
    standard_id = fields.Many2one('sq.standard', string='SQ 기준', required=True, ondelete='cascade', readonly=True)
    area_id = fields.Many2one('sq.area', string='영역', required=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='standard_id.company_id', store=True)
    points = fields.Float('배점', required=True)
    requirement = fields.Text('원문·세부 확인 항목')
    source = fields.Char('원본 위치', readonly=True)
    source_owner = fields.Char('원본 담당', readonly=True)
    responsible_id = fields.Many2one('res.users', string='담당자')
    applicability_note = fields.Char('해당 여부 참고', readonly=True)
    requirement_ids = fields.Many2many('sq.doc.requirement', 'sq_requirement_item_rel', 'item_id', 'requirement_id', string='준비서류')
    rule_ids = fields.One2many('sq.evidence.rule', 'item_id', string='증빙 규칙')
    ready_rate = fields.Float('준비율 (%)', compute='_compute_readiness')
    _sql_constraints = [('item_key', 'unique(standard_id, code)', '같은 개정에 항목 코드 중복입니다.'),
                        ('positive_points', 'check(points >= 0)', '배점은 음수일 수 없습니다.')]

    @api.depends('requirement_ids.state')
    def _compute_readiness(self):
        for item in self:
            reqs = item.requirement_ids
            item.ready_rate = 100 * len(reqs.filtered(lambda r: r.state == 'ready')) / len(reqs) if reqs else 0

    @api.constrains('area_id', 'standard_id')
    def _check_area(self):
        for item in self:
            if item.area_id.standard_id != item.standard_id:
                raise ValidationError(_('같은 기준 개정의 영역만 연결할 수 있습니다.'))

    def write(self, vals):
        if {'code', 'standard_id'} & vals.keys():
            raise UserError(_('안정 코드와 개정은 변경할 수 없습니다.'))
        if {'name', 'points', 'requirement', 'number', 'area_id'} & vals.keys():
            if self.env['sq.assessment.line'].search_count([('item_id', 'in', self.ids)]):
                raise UserError(_('평가에 사용한 항목은 새 개정으로 변경하십시오.'))
        return super().write(vals)

    def action_evidence(self):
        self.ensure_one()
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': self.code + ' 증빙 후보',
                'res_model': 'sq.evidence.rule', 'view_mode': 'list',
                'views': [(self.env.ref('cams_sq.view_evidence_readonly').id, 'list')],
                'domain': [('item_id', '=', self.id)],
                'context': dict(self.env.context, create=False, edit=False, delete=False)}


class SqAlias(models.Model):
    _name = 'sq.item.alias'
    _description = 'SQ 개정별 번호 별칭'
    item_id = fields.Many2one('sq.item', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='item_id.company_id', store=True)
    standard_id = fields.Many2one(related='item_id.standard_id', store=True)
    revision = fields.Char('원본 개정', required=True)
    number = fields.Char('원본 번호', required=True)
    source = fields.Char('매핑 근거')
    _sql_constraints = [('alias_key', 'unique(standard_id,revision,number)', '같은 기준에서 원본 번호가 두 항목으로 연결될 수 없습니다.')]


class SqRequirement(models.Model):
    _name = 'sq.doc.requirement'
    _description = 'SQ 준비 확인'
    _inherit = ['mail.thread']
    _check_company_auto = True
    name = fields.Char('준비 항목', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    source_key = fields.Char(required=True, readonly=True)
    source = fields.Char('원본 위치', readonly=True)
    source_status = fields.Char('원본 과거 표시', readonly=True)
    source_owner = fields.Char('원본 담당', readonly=True)
    source_quantity = fields.Char('원본 구매 수량', readonly=True)
    kind = fields.Selection([('document', '서류'), ('purchase', '구매 준비')], string='준비 구분', required=True, default='document')
    item_ids = fields.Many2many('sq.item', 'sq_requirement_item_rel', 'requirement_id', 'item_id', string='SQ 항목', check_company=True)
    responsible_id = fields.Many2one('res.users', string='현재 담당')
    document_ids = fields.Many2many('iatf.document', string='기존 증빙 문서', check_company=True)
    state = fields.Selection([('todo', '미확인'), ('progress', '준비 중'), ('ready', '준비 확인')], string='준비 상태', default='todo', required=True, tracking=True)
    note = fields.Text('확인 근거', tracking=True)
    _sql_constraints = [('requirement_key', 'unique(company_id,source_key)', '원본 행 중복입니다.')]

    @api.constrains('state', 'document_ids', 'note', 'kind')
    def _check_ready(self):
        for rec in self.filtered(lambda r: r.state == 'ready'):
            if not rec.note or not rec.note.strip():
                raise ValidationError(_('준비 확인 근거를 입력하십시오.'))
            if rec.kind == 'document' and not rec.document_ids:
                raise ValidationError(_('기존 문서관리의 증빙 문서를 연결하십시오.'))
