from odoo import api,fields,models,_
from odoo.exceptions import UserError
from odoo.addons.iatf_document_control.models.inspection_evidence import _lock

_PLAN_FIELDS={'quality_activity_year','quality_training_planned_date','quality_check_planned_date','quality_target_department_ids'}


class ActivityPlanDocument(models.Model):
    _inherit='iatf.document'
    quality_evidence_kind=fields.Selection(selection_add=[('quality_activity_plan','정성품질 연간 계획')],ondelete={'quality_activity_plan':'set null'})
    quality_activity_year=fields.Integer('정성품질 계획 연도',tracking=True)
    quality_training_planned_date=fields.Date('연간 교육 계획일',tracking=True)
    quality_check_planned_date=fields.Date('연간 점검 계획일',tracking=True)
    quality_target_department_ids=fields.Many2many('hr.department',string='정성품질 대상 부서',tracking=True)
    quality_activity_ids=fields.One2many('cams.quality.activity','plan_document_id',string='정성품질 실행',readonly=True,groups='cams_quality_activity.group_activity_user')
    quality_activity_training_count=fields.Integer('검증 완료 교육 건수',compute='_compute_activity_counts',groups='cams_quality_activity.group_activity_user')
    quality_activity_check_count=fields.Integer('검증 완료 점검 건수',compute='_compute_activity_counts',groups='cams_quality_activity.group_activity_user')
    quality_activity_award_count=fields.Integer('검증 완료 부서 포상 건수',compute='_compute_activity_counts',groups='cams_quality_activity.group_activity_user')
    def _quality_evidence_fields(self):return super()._quality_evidence_fields() | _PLAN_FIELDS
    @api.depends('quality_activity_ids.evidence_state','quality_activity_ids.activity_type')
    def _compute_activity_counts(self):
        for doc in self:
            counts={'training':0,'inspection':0,'award':0}
            rows=self.env['cams.quality.activity'].search([('plan_document_id','=',doc.id),('evidence_state','=','done')])
            for row in rows:counts[row.activity_type]+=1
            doc.quality_activity_training_count=counts['training']
            doc.quality_activity_check_count=counts['inspection']
            doc.quality_activity_award_count=counts['award']
    def _check_approval_actor(self):
        super()._check_approval_actor()
        for doc in self.filtered(lambda r:r.quality_evidence_kind=='quality_activity_plan'):
            if (not 2000<=doc.quality_activity_year<=2200 or not doc.quality_target_department_ids
                or not doc.quality_training_planned_date or not doc.quality_check_planned_date
                or doc.quality_training_planned_date.year!=doc.quality_activity_year or doc.quality_check_planned_date.year!=doc.quality_activity_year):
                raise UserError(_('연간 계획 연도·대상 부서·교육 및 점검 계획일을 입력하십시오.'))
            if any(dept.company_id and dept.company_id!=doc.company_id for dept in doc.quality_target_department_ids):
                raise UserError(_('대상 부서는 계획 회사와 같아야 합니다.'))
            if not self.env.user.has_group('cams_ops_policy.group_approver_executive') or self.env.user in (doc.owner_id|doc.create_uid):
                raise UserError(_('정성품질 연간 계획은 작성자와 다른 경영 승인자가 승인합니다.'))


class QualityActivity(models.Model):
    _name='cams.quality.activity'
    _inherit=['cams.evidence.mixin']
    _description='정성품질 교육·점검·부서 포상 실행'
    _order='record_date desc,id desc'
    plan_document_id=fields.Many2one('iatf.document','승인 연간 계획',required=True,ondelete='restrict',domain=[('quality_evidence_kind','=','quality_activity_plan')])
    document_ids=fields.Many2many(compute='_compute_documents',store=True)
    activity_type=fields.Selection([('training','교육 실적 연결'),('inspection','정성품질 점검'),('award','부서 포상')],string='실행 종류',required=True)
    department_id=fields.Many2one('hr.department','대상·수상 부서',required=True,check_company=True)
    training_ids=fields.Many2many('iatf.training.record',string='기존 교육 실적')
    result_note=fields.Text('실행 결과·포상 사유',required=True)
    improvement_type=fields.Selection([('none','개선 사항 없음'),('behavior','품질 의식·행동'),('standard','표준 준수'),('environment','환경·정리정돈'),('other','기타')],string='개선 유형')
    improvement_note=fields.Text('개선 조치')
    award_month=fields.Char('포상 대상 월(YYYY-MM)')
    @api.depends('plan_document_id')
    def _compute_documents(self):
        for record in self:record.document_ids=record.plan_document_id
    def _evidence_fields(self):
        return super()._evidence_fields() | {'plan_document_id','activity_type','department_id','training_ids','result_note','improvement_type','improvement_note','award_month'}
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            plan=record.plan_document_id
            if (plan.state!='approved' or plan.quality_evidence_kind!='quality_activity_plan' or not plan.quality_evidence_current
                or record.record_date.year!=plan.quality_activity_year or record.department_id not in plan.quality_target_department_ids):
                raise UserError(_('해당 연도·대상 부서의 승인 연간 계획을 선택하십시오.'))
            if record.activity_type=='training':
                if not record.training_ids:raise UserError(_('기존 교육 화면에서 실제 교육을 완료하고 연결하십시오.'))
                record.training_ids.check_access('read');_lock(record.training_ids)
                for training in record.training_ids:
                    if training.company_id!=record.company_id or training.state not in ('completed','verified') or training.training_date.year!=plan.quality_activity_year or training.participant_count<=0:
                        raise UserError(_('회사·연도·참석자가 확인된 완료 교육 실적만 연결할 수 있습니다.'))
                    # Read permission/company were checked above. Validate only
                    # this linked request; don't grant general HR approval access.
                    training.sudo()._approval_check_approved(_('정성품질 교육 실적'))
            elif record.activity_type=='inspection':
                if not record.improvement_type or (record.improvement_type!='none' and not record.improvement_note):
                    raise UserError(_('점검 개선 유형과 필요한 조치를 기록하십시오.'))
            elif record.activity_type=='award':
                import re
                if (not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',record.award_month or '') or int(record.award_month[:4])!=plan.quality_activity_year
                    or record.award_month>record.record_date.strftime('%Y-%m')):
                    raise UserError(_('포상 대상 월은 계획 연도의 YYYY-MM으로 입력하십시오.'))
                lines=record.approval_request_id.line_ids.sorted('sequence')
                if not lines or not lines[-1].user_id.has_group('cams_ops_policy.group_approver_executive'):
                    raise UserError(_('부서 포상의 최종 결재자는 경영 승인자로 지정하십시오.'))
    def _approval_snapshot(self):
        result=super()._approval_snapshot()
        self.training_ids.check_access('read')
        result['training_evidence']=[{'id':row.id,'title':row.title,'date':str(row.training_date),'state':row.state,
            'approval_state':row.approval_state,'participant_count':row.participant_count} for row in self.training_ids.sorted('id')]
        result['department_name']=self.department_id.name
        return result


class Attachment(models.Model):
    _inherit='ir.attachment'
    @api.model
    def _cams_evidence_models(self):return super()._cams_evidence_models()+('cams.quality.activity',)
