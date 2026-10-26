import json
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import file_open
from .specs import SPECS, SOURCE_MODELS

_IMPORT_TOKEN = object()
_CONFIG = {'output_type', 'output_model', 'output_source_hint', 'output_revision',
           'output_priority', 'output_format', 'output_sequence'}


class Requirement(models.Model):
    _inherit = 'sq.doc.requirement'

    output_type = fields.Selection([('report', '보고서'), ('upload', '업로드'),
        ('export', '조회·내보내기'), ('external', '외부·수동')], string='출력 유형', tracking=True)
    output_model = fields.Selection(selection='_output_models', string='출력 원천', tracking=True)
    output_source_hint = fields.Char('인계 원천 표기', readonly=True)
    output_revision = fields.Char('출력 목록 출처', readonly=True)
    output_priority = fields.Char('출력 우선순위', readonly=True)
    output_format = fields.Char('요청 출력 형식', readonly=True)
    output_sequence = fields.Integer('서류 일람 순서', readonly=True)
    output_binding_ids = fields.One2many('sq.output.binding', 'requirement_id', string='출력 원천 연결')

    @api.model
    def _output_models(self):
        return [(key, self.env[key]._description if key in self.env else key + ' (미설치)') for key in sorted(SPECS)]

    def write(self, vals):
        if set(vals) & _CONFIG and not (self.env.su or self.env.user.has_group('cams_sq.group_sq_manager')):
            raise AccessError(_('출력 정의는 SQ 기준 관리자만 변경할 수 있습니다.'))
        if {'output_revision', 'output_source_hint', 'output_sequence'} & set(vals) and self.env.context.get('_sq_output_import') is not _IMPORT_TOKEN:
            raise UserError(_('출력 출처와 순서는 기준 목록 적재로만 변경합니다.'))
        return super().write(vals)

    def action_output(self):
        self.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('서류 출력'), 'res_model': 'sq.output.wizard',
                'view_mode': 'form', 'target': 'new', 'context': dict(self.env.context,
                default_requirement_ids=[(6, 0, self.ids)])}

    @api.model
    def action_load_outputs(self):
        if not (self.env.su or self.env.user.has_group('cams_sq.group_sq_manager')):
            raise AccessError(_('SQ 기준 관리자만 출력 목록을 적재할 수 있습니다.'))
        with self.env.cr.savepoint():
            counts = self._load_outputs()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': _('서류 출력 목록'), 'message': '467건 연결 / 조립 별칭36건 보충. 실제 원천 연결과 준비 상태는 보존합니다. ' + str(counts), 'sticky': True}}

    def _load_outputs(self):
        with file_open('cams_sq_outputs/data/outputs.json', 'r') as source:
            data = json.load(source)
        self.env.cr.execute('SELECT id FROM res_company WHERE id=%s FOR UPDATE', [self.env.company.id])
        counts = {}
        for row in data['outputs']:
            requirement = self.search([('company_id', '=', self.env.company.id), ('source_key', '=', row['source_key'])])
            if len(requirement) != 1 or requirement.name != row['name']:
                raise UserError(_('기존 준비목록의 키·명칭을 확인하십시오: %s') % row['source_key'])
            counts[row['output_type']] = counts.get(row['output_type'], 0) + 1
            if requirement.output_revision:
                if requirement.output_revision != data['source_commit']:
                    raise UserError(_('출력 목록의 출처 개정이 다릅니다. 변경 검토가 필요합니다.'))
                continue  # Never reset a user's subsequent explicit source choice.
            requirement.with_context(_sq_output_import=_IMPORT_TOKEN).write({
                'output_type': row['output_type'], 'output_model': row['output_model'] or False,
                'output_source_hint': row['source_hint'], 'output_revision': data['source_commit'],
                'output_priority': row['priority'], 'output_format': row['format'],
                'output_sequence': row['sequence']})
        standard = self.env['sq.standard'].search([('company_id', '=', self.env.company.id),
            ('sector', '=', 'ASM'), ('revision', '=', '2026-10-union')])
        if len(standard) != 1:
            raise UserError(_('전기조립 합집합 기준을 먼저 적재하십시오.'))
        for row in data['asm_aliases']:
            item = standard.item_ids.filtered(lambda i: i.code == 'ASM.' + row['union_code'])
            if len(item) != 1:
                raise UserError(_('전기조립 별칭의 대응 항목이 없습니다.'))
            alias = self.env['sq.item.alias'].search([('standard_id', '=', standard.id),
                ('revision', '=', row['source']), ('number', '=', row['external_code'])])
            if alias and alias.item_id != item:
                raise UserError(_('전기조립 별칭이 다른 항목과 충돌합니다.'))
            if not alias:
                self.env['sq.item.alias'].create({'item_id': item.id, 'revision': row['source'],
                    'number': row['external_code'], 'source': row['source'],
                    'external_code': row['external_code'], 'basis': row['basis']})
        return counts


class OutputBinding(models.Model):
    _name = 'sq.output.binding'
    _description = 'SQ 서류별 기존 원천 범위'
    _check_company_auto = True
    _rec_name = 'purpose'

    requirement_id = fields.Many2one('sq.doc.requirement', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='requirement_id.company_id', store=True)
    source_ref = fields.Reference(selection='_source_models', string='실제 원천/점검 대상', required=True)
    purpose = fields.Char('이 서류와 연결하는 근거', required=True)
    active = fields.Boolean(default=True)
    _sql_constraints = [('source_unique', 'unique(requirement_id,source_ref)', '같은 원천을 중복 연결할 수 없습니다.')]

    @api.model
    def _source_models(self):
        return [(key, self.env[key]._description) for key in SOURCE_MODELS if key in self.env]

    @api.constrains('source_ref', 'requirement_id', 'purpose')
    def _check_source(self):
        for binding in self:
            source = binding.source_ref.exists() if binding.source_ref else False
            if not source or source._name not in SOURCE_MODELS or not (binding.purpose or '').strip():
                raise ValidationError(_('존재하는 원천과 구체적인 연결 근거가 필요합니다.'))
            source.check_access('read')
            binding.requirement_id.check_access('read')
            from .output import source_company
            company = source_company(source)
            if not company or company != binding.company_id or company not in self.env.companies:
                raise AccessError(_('회사 경계가 확인된 같은 회사 원천만 연결하십시오.'))

    def action_open_source(self):
        self.ensure_one()
        self.check_access('read')
        self._check_source()
        return {'type': 'ir.actions.act_window', 'res_model': self.source_ref._name,
                'res_id': self.source_ref.id, 'view_mode': 'form'}
