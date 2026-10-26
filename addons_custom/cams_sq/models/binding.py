from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class SqEvidenceBinding(models.Model):
    """Classification of existing sources, never a second inspection ledger."""
    _name = 'sq.evidence.binding'
    _description = 'SQ 항목별 기존 증빙 연결'
    _check_company_auto = True
    _rec_name = 'purpose'

    item_id = fields.Many2one('sq.item', string='SQ 항목', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='item_id.company_id', store=True)
    source_ref = fields.Reference(selection='_source_models', string='기존 점검 시트 또는 문서', required=True)
    purpose = fields.Char('이 항목의 증빙으로 연결하는 근거', required=True)
    active = fields.Boolean(default=True)
    _sql_constraints = [('binding_key', 'unique(item_id,source_ref)', '같은 항목에 같은 원천을 중복 연결할 수 없습니다.')]

    @api.model
    def _source_models(self):
        return [(name, self.env[name]._description) for name in ('iatf.check.sheet', 'iatf.document') if name in self.env]

    @api.constrains('source_ref', 'item_id', 'purpose')
    def _check_source(self):
        for binding in self:
            source = binding.source_ref.exists() if binding.source_ref else False
            if not source or source._name not in dict(binding._source_models()):
                raise ValidationError(_('존재하는 점검 시트 또는 문서만 연결하십시오.'))
            source.check_access('read')
            binding.item_id.check_access('read')
            if binding.company_id not in self.env.companies or source.company_id != binding.company_id:
                raise AccessError(_('SQ 항목과 같은 회사의 원천만 연결할 수 있습니다.'))
            if not (binding.purpose or '').strip():
                raise ValidationError(_('원천을 이 SQ 항목에 연결하는 근거를 입력하십시오.'))

    def action_open_source(self):
        self.ensure_one()
        self.check_access('read')
        self._check_source()
        return {'type': 'ir.actions.act_window', 'name': self.purpose,
                'res_model': self.source_ref._name, 'res_id': self.source_ref.id, 'view_mode': 'form',
                'context': dict(self.env.context, create=False, edit=False, delete=False)}


class SqItemBinding(models.Model):
    _inherit = 'sq.item'
    binding_ids = fields.One2many('sq.evidence.binding', 'item_id', string='기존 점검 시트·문서 연결')

    def _bound_source_ids(self, model):
        self.ensure_one()
        self.check_access('read')
        ids = []
        for binding in self.binding_ids.filtered('active'):
            binding.check_access('read')
            source = binding.source_ref
            if source and source._name == model and source.exists():
                source.check_access('read')
                if source.company_id == self.company_id:
                    ids.append(source.id)
        if model == 'iatf.document':
            for document in self.requirement_ids.mapped('document_ids'):
                document.check_access('read')
                if document.company_id == self.company_id:
                    ids.append(document.id)
        return list(set(ids))
