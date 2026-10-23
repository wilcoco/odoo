from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.iatf_document_control.models.inspection_evidence import _lock


class QualificationCriteria(models.Model):
    _inherit = 'iatf.document'

    quality_evidence_kind = fields.Selection(
        selection_add=[('qualification_criteria', '작업자 자격 사전평가 기준')],
        ondelete={'qualification_criteria': 'set null'})
    qualification_criteria_confirmed = fields.Boolean('실제 자격 기준 확인', tracking=True)
    qualification_theory_min = fields.Float('이론 최소 점수(100점)', tracking=True)
    qualification_practical_min = fields.Float('실기 최소 점수(100점)', tracking=True)
    qualification_method = fields.Text('시험 방법·필수 관찰 항목', tracking=True)

    def _quality_evidence_fields(self):
        return super()._quality_evidence_fields() | {
            'qualification_criteria_confirmed', 'qualification_theory_min',
            'qualification_practical_min', 'qualification_method'}

    def _check_approval_actor(self):
        super()._check_approval_actor()
        for doc in self.filtered(lambda d: d.quality_evidence_kind == 'qualification_criteria'):
            if (not doc.qualification_criteria_confirmed or not doc.qualification_method
                    or not 0 < doc.qualification_theory_min <= 100
                    or not 0 < doc.qualification_practical_min <= 100):
                raise UserError(_('실제 시험 방법과 이론·실기 합격 기준(0 초과, 100 이하)을 확인하십시오.'))


class QualificationPreassessment(models.Model):
    _name = 'iatf.qualification.preassessment'
    _inherit = ['cams.evidence.mixin']
    _description = '작업자 자격 사전평가 이력'
    _order = 'record_date desc, id desc'

    competence_id = fields.Many2one('iatf.competence.matrix', '기존 직원·역량', required=True, ondelete='restrict')
    criteria_document_id = fields.Many2one('iatf.document', '승인된 자격 기준', required=True, ondelete='restrict',
        domain=[('quality_evidence_kind', '=', 'qualification_criteria')])
    document_ids = fields.Many2many(compute='_compute_documents', store=True)
    theory_score = fields.Float('이론 점수(100점)')
    practical_score = fields.Float('실기 점수(100점)')
    assessed_level = fields.Selection([
        ('0', '미교육'), ('1', '인지'), ('2', '감독하 수행'),
        ('3', '독립 수행'), ('4', '타인 교육')], string='평가 수준', required=True)
    observation = fields.Text('실기 관찰·평가 근거', required=True)
    result = fields.Selection([('pass', '적합'), ('fail', '부적합')], string='평가 결과', required=True)
    followup = fields.Text('재교육·재평가 계획')

    @api.depends('criteria_document_id')
    def _compute_documents(self):
        for record in self:
            record.document_ids = record.criteria_document_id

    def _evidence_fields(self):
        return super()._evidence_fields() | {
            'competence_id', 'criteria_document_id', 'theory_score', 'practical_score',
            'assessed_level', 'observation', 'result', 'followup'}

    @api.constrains('competence_id', 'company_id')
    def _check_competence_company(self):
        for record in self:
            record.competence_id.check_access('read')
            # Read only company/user metadata after the matrix record rule; no HR
            # permissions or employee personal data are exposed to this role.
            employee = record.competence_id.sudo().employee_id
            if employee.company_id != record.company_id:
                raise ValidationError(_('직원 역량과 평가 회사가 다릅니다.'))

    def _evidence_validate(self):
        super()._evidence_validate()
        self._check_competence_company()
        for record in self:
            criteria = record.criteria_document_id
            if (criteria.state != 'approved' or not criteria.quality_evidence_current
                    or criteria.quality_evidence_kind != 'qualification_criteria'
                    or not criteria.qualification_criteria_confirmed):
                raise UserError(_('현재 유효하고 실제 기준이 확인된 승인 자격 기준을 선택하십시오.'))
            if not record.attachment_ids or not record.observation.strip():
                raise UserError(_('실제 시험지·실기 기록과 평가 근거를 첨부하십시오.'))
            if not (0 <= record.theory_score <= 100 and 0 <= record.practical_score <= 100):
                raise UserError(_('이론·실기 점수는 0~100 범위입니다.'))
            _lock(record.competence_id)
            qualifies = (record.theory_score >= criteria.qualification_theory_min
                and record.practical_score >= criteria.qualification_practical_min
                and int(record.assessed_level) >= int(record.competence_id.required_level or '0'))
            if record.result == 'pass' and not qualifies:
                raise UserError(_('이론·실기 점수 또는 요구 수준 미달은 적합으로 완료할 수 없습니다.'))
            if record.result == 'fail' and not (record.followup or '').strip():
                raise UserError(_('부적합 사전평가에는 재교육·재평가 계획이 필요합니다.'))
            employee_user = record.competence_id.sudo().employee_id.user_id
            if employee_user and employee_user in record.approval_request_id.line_ids.user_id:
                raise UserError(_('평가 대상자가 자신의 자격 평가를 승인할 수 없습니다.'))

    def _approval_snapshot(self):
        result = super()._approval_snapshot()
        self.competence_id.check_access('read')
        matrix = self.competence_id
        result['competence'] = {'id': matrix.id, 'employee_id': matrix.employee_id.id,
            'label': matrix.display_name, 'skill_name': matrix.skill_name,
            'required_level': matrix.required_level, 'current_level': matrix.current_level}
        return result


class Attachment(models.Model):
    _inherit = 'ir.attachment'

    @api.model
    def _cams_evidence_models(self):
        return super()._cams_evidence_models() + ('iatf.qualification.preassessment',)
