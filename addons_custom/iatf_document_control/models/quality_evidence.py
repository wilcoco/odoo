"""Structured quality evidence on the controlled document, not a second SQ ledger."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .document import _WORKFLOW_CONTEXT, _WORKFLOW_TOKEN

_QUALITY_FIELDS = {
    'quality_evidence_kind', 'quality_product_ids', 'physical_reference', 'storage_location',
    'quality_valid_from', 'quality_valid_until', 'quality_cycle_note',
    'quality_participant_count', 'quality_reward_reference',
}


class QualityEvidence(models.Model):
    _inherit = 'iatf.document'

    quality_evidence_kind = fields.Selection([
        ('limit_sample', '한도견본'), ('reliability_plan', '정기·신뢰성 시험 계획'),
        ('equipment_standard', '건조·분쇄·배합 설비 기준'), ('container_standard', '용기·포장 기준'),
        ('drawing_agreement', '도면·검사 협정'), ('quality_activity', '정성품질 활동·참여·포상'),
    ], string='품질 증빙 용도', tracking=True)
    quality_product_ids = fields.Many2many('product.product', string='적용 품번', tracking=True)
    physical_reference = fields.Char(string='실물·견본 식별번호', tracking=True)
    storage_location = fields.Char(string='견본·기준 보관 위치', tracking=True)
    quality_valid_from = fields.Date(string='유효 시작일', tracking=True)
    quality_valid_until = fields.Date(string='유효 종료일', tracking=True)
    quality_cycle_note = fields.Char(string='점검·시험 주기 및 기준', tracking=True)
    quality_participant_count = fields.Integer(string='활동 참여 인원', tracking=True)
    quality_reward_reference = fields.Char(string='포상·참여 근거 문서번호', tracking=True)
    quality_evidence_current = fields.Boolean(string='현재 유효한 승인 기준', compute='_compute_quality_current', search='_search_quality_current')

    def _quality_evidence_fields(self):
        return _QUALITY_FIELDS

    def _quality_evidence_snapshot(self):
        self.ensure_one()
        return {name:sorted(self[name].ids) if self._fields[name].relational else str(self[name])
            if self._fields[name].type in ('date','datetime') and self[name] else self[name]
            for name in sorted(self._quality_evidence_fields())}

    @api.depends('state', 'active', 'quality_valid_from', 'quality_valid_until')
    def _compute_quality_current(self):
        today = fields.Date.context_today(self)
        for doc in self:
            doc.quality_evidence_current = bool(doc.active and doc.state == 'approved'
                and (not doc.quality_valid_from or doc.quality_valid_from <= today)
                and (not doc.quality_valid_until or doc.quality_valid_until >= today))

    @api.model
    def _search_quality_current(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('유효 기준 여부는 참/거짓으로 검색하십시오.'))
        from odoo.osv import expression
        today = fields.Date.context_today(self)
        domain = [('active', '=', True), ('state', '=', 'approved'),
            '|', ('quality_valid_from', '=', False), ('quality_valid_from', '<=', today),
            '|', ('quality_valid_until', '=', False), ('quality_valid_until', '>=', today)]
        return domain if value == (operator == '=') else expression.distribute_not(['!'] + expression.normalize_domain(domain))

    @api.constrains('quality_valid_from', 'quality_valid_until', 'quality_participant_count', 'quality_product_ids', 'company_id')
    def _check_quality_scope(self):
        for doc in self:
            if doc.quality_valid_from and doc.quality_valid_until and doc.quality_valid_from > doc.quality_valid_until:
                raise ValidationError(_('유효 종료일은 시작일보다 빠를 수 없습니다.'))
            if doc.quality_participant_count < 0:
                raise ValidationError(_('참여 인원은 음수일 수 없습니다.'))
            if any(p.company_id and p.company_id != doc.company_id for p in doc.quality_product_ids):
                raise ValidationError(_('다른 회사의 품번을 연결할 수 없습니다.'))

    def write(self, vals):
        if self._quality_evidence_fields() & vals.keys() and self.env.context.get(_WORKFLOW_CONTEXT) is not _WORKFLOW_TOKEN:
            self._lock_document()
            if any(doc.state != 'draft' for doc in self):
                raise UserError(_('승인 기준·견본 정보는 새 개정 또는 회수 후 변경하십시오.'))
        return super().write(vals)

    def _check_approval_actor(self):
        super()._check_approval_actor()
        for doc in self:
            if doc.quality_evidence_kind == 'limit_sample' and not all((doc.physical_reference,
                    doc.storage_location, doc.quality_product_ids, doc.quality_valid_until)):
                raise UserError(_('한도견본에는 식별번호·보관 위치·적용 품번·유효 종료일이 필요합니다.'))
            if doc.quality_evidence_kind == 'reliability_plan' and not (doc.quality_product_ids and doc.quality_cycle_note):
                raise UserError(_('시험 계획에는 적용 품번과 주기·기준을 입력하십시오.'))

    def action_new_revision(self):
        self.ensure_one()
        metadata = self._quality_evidence_snapshot()
        result = super().action_new_revision()
        self.revision_ids.sorted('id')[-1:].with_context(**{_WORKFLOW_CONTEXT: _WORKFLOW_TOKEN}).write({'quality_metadata': metadata})
        return result


class QualityEvidenceRevision(models.Model):
    _inherit = 'iatf.document.revision'
    quality_metadata = fields.Json(string='당시 품질 증빙 기준', readonly=True)
