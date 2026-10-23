from odoo import api,fields,models,_
from odoo.exceptions import AccessError,UserError
from odoo.addons.cams_evidence_core.models.evidence import _CTX,_TOKEN
from odoo.addons.iatf_document_control.models.inspection_evidence import _lock

_SPEC_FIELDS={'part_number','customer_id','revision','effective_date','inner_packaging_type','inner_quantity','inner_material',
    'inner_dimension','outer_packaging_type','outer_quantity','outer_material','outer_dimension','gross_weight','pallet_type',
    'boxes_per_pallet','pallet_stack','label_required','label_type','label_info','storage_condition','temperature_range',
    'humidity_range','shelf_life_days','special_instruction','anticorrosion_method','customer_approved','approval_date',
    'approval_reference','notes','image','flow_direction','automated','t1_date','automation_ready_date','readiness_deviation'}
_CHECKS=('cleanliness','damage','identification','mixed_parts')
_CHOICES=[('ok','정상'),('ng','이상')]


class PackagingSpec(models.Model):
    _name='iatf.packaging.spec'
    _inherit=['cams.evidence.mixin','iatf.packaging.spec']
    flow_direction=fields.Selection([('customer','원청 납입'),('internal','사내 공정'),('return','회수·공용')],string='용기 흐름',tracking=True)
    automated=fields.Boolean('자동화 대응 용기',tracking=True)
    t1_date=fields.Date('T1 일정',tracking=True)
    automation_ready_date=fields.Date('자동화 용기 준비일',tracking=True)
    readiness_deviation=fields.Text('T1 30일 전 미충족 조치',tracking=True)
    def _evidence_fields(self):return super()._evidence_fields() | _SPEC_FIELDS
    def _approval_reset_ignored_fields(self):return super()._approval_reset_ignored_fields() | {'state'}
    def _evidence_completion_values(self):return dict(super()._evidence_completion_values(),state='active')
    def _evidence_revision_values(self):return dict(super()._evidence_revision_values(),state='draft')

    @api.model_create_multi
    def create(self,vals_list):
        if not self._evidence_internal():
            for values in vals_list:
                if values.get('state',self.env.context.get('default_state','draft'))!='draft':
                    raise UserError(_('용기 기준은 초안으로 작성하고 승인 후 활성화합니다.'))
        return super().create(vals_list)
    def write(self,values):
        if not self._evidence_internal():
            if 'state' in values:raise UserError(_('용기 사양 상태는 승인·폐기 절차로만 변경합니다.'))
            if self._evidence_fields() & values.keys() and any(r.state in ('active','obsolete') for r in self):
                raise UserError(_('활성·폐기한 용기 기준은 새 개정으로 수정하십시오.'))
        return super().write(values)
    def unlink(self):
        if any(r.state in ('active','obsolete') for r in self):raise UserError(_('사용한 용기 기준은 삭제하지 않습니다.'))
        return super().unlink()
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if record.state!='draft' or not record.flow_direction or not record.outer_packaging_type or record.outer_quantity<=0:
                raise UserError(_('초안에 용기 흐름·종류·수용 수량을 기록하십시오.'))
            if record.customer_id and not (record.customer_approved and record.approval_reference and record.approval_date):
                raise UserError(_('고객 지정 사양에는 고객 승인 문서번호·일자가 필요합니다.'))
            if record.approval_date and record.approval_date>fields.Date.context_today(record):
                raise UserError(_('고객 승인일은 미래일 수 없습니다.'))
            if record.automated:
                if not record.t1_date or not record.automation_ready_date:raise UserError(_('T1·자동화 준비일을 입력하십시오.'))
                if (record.t1_date-record.automation_ready_date).days<30 and not record.readiness_deviation:
                    raise UserError(_('T1 30일 전 준비 미충족 사유와 조치를 기록하십시오.'))
    def action_activate(self):
        return self.action_complete_evidence()
    def action_complete_evidence(self):
        # The core completion is also called directly from RPC; keep the same
        # single-family activation transition in both entry points.
        unfinished=self.filtered(lambda r:r.evidence_state!='done')
        result=super().action_complete_evidence()
        for record in unfinished:
            self.search([('evidence_key','=',record.evidence_key),('id','!=',record.id),('state','=','active')]).with_context(**{_CTX:_TOKEN}).write({'state':'obsolete'})
        return result
    def action_review(self):
        raise UserError(_('승인한 용기 기준은 정정 개정을 작성하여 검토하십시오.'))
    def action_obsolete(self):
        if not self.env.user.has_group('iatf_packaging.group_packaging_manager'):raise AccessError(_('용기 기준 책임자가 폐기 처리합니다.'))
        self._approval_lock()
        return self.with_context(**{_CTX:_TOKEN}).write({'state':'obsolete'})
    def action_new_evidence_revision(self):
        self.ensure_one()
        if self.evidence_state=='done':return super().action_new_evidence_revision()
        self._approval_lock()
        if self.state!='active':raise UserError(_('활성한 기존 기준에서 정정 개정을 만듭니다.'))
        if self.search_count([('previous_evidence_id','=',self.id)]):raise UserError(_('이미 만든 정정 개정을 사용하십시오.'))
        new=self.with_context(**{_CTX:_TOKEN}).copy({'evidence_key':self.evidence_key,'evidence_revision':self.evidence_revision+1,
            'previous_evidence_id':self.id,'state':'draft','evidence_state':'draft'})
        return {'type':'ir.actions.act_window','res_model':self._name,'res_id':new.id,'view_mode':'form','target':'current'}


class ContainerClean(models.Model):
    _name='cams.container.clean'
    _inherit=['cams.evidence.mixin']
    _description='분기 용기 점검·사양 대조'
    _order='record_date desc,id desc'
    spec_id=fields.Many2one('iatf.packaging.spec','승인 용기 사양',required=True,ondelete='restrict',check_company=True)
    quarter=fields.Selection([('1','1분기'),('2','2분기'),('3','3분기'),('4','4분기')],string='점검 분기',compute='_compute_quarter')
    cleanliness=fields.Selection(_CHOICES,string='청결',required=True)
    damage=fields.Selection(_CHOICES,string='파손',required=True)
    identification=fields.Selection(_CHOICES,string='식별',required=True)
    mixed_parts=fields.Selection(_CHOICES,string='혼입 방지',required=True)
    actual_container_type=fields.Char('실제 용기 종류',required=True)
    actual_quantity=fields.Integer('실제 수용 수량(EA)')
    action_note=fields.Text('이상·사양 불일치 개선')
    result=fields.Selection([('ok','사양 일치·정상'),('ng','불일치·개선 필요')],string='대조 판정',compute='_compute_result')
    def _evidence_calculated_fields(self):return {'quarter','result'}
    def _evidence_fields(self):return super()._evidence_fields() | set(_CHECKS) | {'spec_id','actual_container_type','actual_quantity','action_note'}
    @api.depends('record_date')
    def _compute_quarter(self):
        for record in self:record.quarter=str((record.record_date.month-1)//3+1) if record.record_date else False
    @api.depends('cleanliness','damage','identification','mixed_parts','actual_container_type','actual_quantity','spec_id.outer_packaging_type','spec_id.outer_quantity','evidence_state','completion_snapshot')
    def _compute_result(self):
        for record in self:
            record.result=((record.completion_snapshot or {}).get('comparison_result','ng') if record.evidence_state=='done'
                else 'ok' if all(record[key]=='ok' for key in _CHECKS) and record.actual_container_type==record.spec_id.outer_packaging_type
                and record.actual_quantity==record.spec_id.outer_quantity else 'ng')
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            spec=record.spec_id
            spec.check_access('read');_lock(spec)
            if spec.company_id!=record.company_id or spec.product_id!=record.product_id or spec.evidence_state!='done' or spec.state!='active':
                raise UserError(_('같은 회사·품번의 승인 활성 용기 사양을 선택하십시오.'))
            if not record.attachment_ids or not record.lot_id or record.actual_quantity<=0:
                raise UserError(_('실물 사진·대상 LOT·실제 수용 수량이 필요합니다.'))
            if record.result=='ng' and not (record.action_note or '').strip():raise UserError(_('사양 불일치·이상에는 개선 내용을 기록하십시오.'))
    def _approval_snapshot(self):
        result=super()._approval_snapshot()
        self.spec_id.check_access('read')
        result['specification']=self.spec_id.completion_snapshot
        result['comparison_result']=self.result
        return result


class Attachment(models.Model):
    _inherit='ir.attachment'
    @api.model
    def _cams_evidence_models(self):return super()._cams_evidence_models()+('iatf.packaging.spec','cams.container.clean')
