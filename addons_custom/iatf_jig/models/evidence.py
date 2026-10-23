from odoo import api,fields,models,_
from odoo.exceptions import AccessError,UserError

_TOKEN=object()
_CTX='_iatf_jig_disposition'
_JIG_CRITERIA={'quality_jig_dimensions_required','quality_jig_limit_mm','quality_jig_method'}
_VISUAL=('cleanliness','seating','shape','surface','bolts')
_OK_NG=[('ok','정상'),('ng','이상')]


class Document(models.Model):
    _inherit='iatf.document'
    quality_evidence_kind=fields.Selection(selection_add=[('jig_standard','지그 점검 기준')],ondelete={'jig_standard':'set null'})
    quality_jig_dimensions_required=fields.Boolean('지그 치수 검증 포함',tracking=True)
    quality_jig_limit_mm=fields.Float('확정 치수 한계(mm)',tracking=True,
        help='타사 참고 10mm를 자동 적용하지 않습니다. 치수 검증이 필요한 경우 확인된 한계를 입력하십시오.')
    quality_jig_method=fields.Text('지그 5항목·측정 방법',tracking=True)
    def _quality_evidence_fields(self):return super()._quality_evidence_fields() | _JIG_CRITERIA
    def _check_approval_actor(self):
        super()._check_approval_actor()
        for doc in self.filtered(lambda d:d.quality_evidence_kind=='jig_standard'):
            if not doc.quality_jig_method or not doc.quality_product_ids or (doc.quality_jig_dimensions_required and doc.quality_jig_limit_mm<=0):
                raise UserError(_('지그 적용 품번·점검 방법·필요한 치수 한계를 확인하십시오.'))


class Jig(models.Model):
    _inherit='iatf.jig'
    use_blocked=fields.Boolean('이상 지그 사용 금지',readonly=True,copy=False,tracking=True)
    blocked_record_id=fields.Many2one('iatf.jig.record','사용 금지 점검',readonly=True,copy=False,ondelete='restrict')
    released_record_id=fields.Many2one('iatf.jig.record','재사용 검증 기록',readonly=True,copy=False,ondelete='restrict')
    blocked_at=fields.Datetime('사용 금지 시각',readonly=True,copy=False)
    release_candidate_id=fields.Many2one('iatf.jig.record','재사용 검증 선택',domain="[('jig_id','=',id),('record_type','=','verification'),('evidence_state','=','done')]",copy=False)

    @api.model_create_multi
    def create(self,vals_list):
        for values in vals_list:
            if any(key in values or 'default_'+key in self.env.context for key in ('use_blocked','blocked_record_id','released_record_id','blocked_at')):
                raise UserError(_('지그 사용 금지·해제 근거를 직접 생성하지 않습니다.'))
        return super().create(vals_list)

    def write(self,values):
        self._approval_lock()
        if self.env.context.get(_CTX) is not _TOKEN:
            if {'use_blocked','blocked_record_id','released_record_id','blocked_at'} & values.keys():
                raise UserError(_('지그 사용 금지·해제는 점검과 재검증 승인으로만 처리합니다.'))
            if values.get('state')=='active' and any(r.use_blocked for r in self):
                raise UserError(_('이상 지그는 재검증 승인 전 사용할 수 없습니다.'))
        return super().write(values)

    def action_release_verified(self):
        if not self.env.user.has_group('iatf_jig.group_jig_manager'):
            raise AccessError(_('지그 책임자만 재검증 결과로 사용 금지를 해제합니다.'))
        for jig in self:
            jig._approval_lock()
            check=jig.release_candidate_id
            if not jig.use_blocked:continue
            check._approval_lock()
            if (not check or check.jig_id!=jig or check.evidence_state!='done' or check.record_type!='verification'
                or check.status!='normal' or check.completed_at<jig.blocked_at
                or (check.completion_snapshot or {}).get('jig_block_id')!=jig.blocked_record_id.id):
                raise UserError(_('사용 금지 이후 완료한 정상 재검증 기록이 필요합니다.'))
            check._approval_check_approved(_('지그 재사용'))
            if check._approval_snapshot()!=check.completion_snapshot:
                raise UserError(_('재검증 이후 기준·원천 정보가 바뀌었습니다. 다시 검증하십시오.'))
            jig.with_context(**{_CTX:_TOKEN}).write({'use_blocked':False,'released_record_id':check.id,'state':'active'})
        return True


class JigRecord(models.Model):
    _name='iatf.jig.record'
    _inherit=['cams.evidence.mixin','iatf.jig.record']
    jig_id=fields.Many2one(ondelete='restrict')
    product_id=fields.Many2one('product.product','점검 당시 품번',check_company=True)
    responsible_id=fields.Many2one(related='performer_id',store=True,readonly=False,default=None,precompute=True)
    standard_document_id=fields.Many2one('iatf.document','승인 점검 기준',ondelete='restrict',domain=[('quality_evidence_kind','=','jig_standard')])
    document_ids=fields.Many2many(compute='_compute_documents',store=True)
    cleanliness=fields.Selection(_OK_NG,string='청결 상태')
    seating=fields.Selection(_OK_NG,string='안착 상태')
    shape=fields.Selection(_OK_NG,string='형상 상태')
    surface=fields.Selection(_OK_NG,string='표면 상태')
    bolts=fields.Selection(_OK_NG,string='볼트 상태')
    measured_1_mm=fields.Float('1개소 측정(mm)')
    measured_2_mm=fields.Float('2개소 측정(mm)')
    measured_3_mm=fields.Float('3개소 측정(mm)')
    measured_4_mm=fields.Float('4개소 측정(mm)')
    dimensions_confirmed=fields.Boolean('4개소 실측 확인')
    @api.model_create_multi
    def create(self,vals_list):
        for values in vals_list:
            jig=self.env['iatf.jig'].browse(values.get('jig_id',self.env.context.get('default_jig_id')))
            if jig and 'product_id' not in values:values['product_id']=jig.product_id.id
        return super().create(vals_list)
    @api.depends('standard_document_id')
    def _compute_documents(self):
        for record in self:record.document_ids=record.standard_document_id
    def _evidence_fields(self):
        return super()._evidence_fields() | set(_VISUAL) | {'jig_id','record_type','status','measured_values','remarks','performer_id',
            'standard_document_id','measured_1_mm','measured_2_mm','measured_3_mm','measured_4_mm','dimensions_confirmed'}
    def _approval_snapshot(self):
        result=super()._approval_snapshot()
        result['jig_block_id']=self.jig_id.blocked_record_id.id
        return result
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            doc=record.standard_document_id
            if (doc.state!='approved' or doc.quality_evidence_kind!='jig_standard' or not doc.quality_evidence_current
                or record.product_id not in doc.quality_product_ids or record.product_id!=record.jig_id.product_id
                or record.jig_id.company_id!=record.company_id):
                raise UserError(_('같은 회사·품번에 적용되는 승인 지그 기준을 선택하십시오.'))
            if not all(record[key] for key in _VISUAL) or not record.status:
                raise UserError(_('청결·안착·형상·표면·볼트 5항목을 확인하십시오.'))
            normal=all(record[key]=='ok' for key in _VISUAL)
            if doc.quality_jig_dimensions_required:
                if not record.dimensions_confirmed:raise UserError(_('4개소를 실제 측정한 뒤 확인하십시오.'))
                normal=normal and all(0<=record[key]<=doc.quality_jig_limit_mm for key in ('measured_1_mm','measured_2_mm','measured_3_mm','measured_4_mm'))
            if (record.status=='normal')!=normal:
                raise UserError(_('5항목·실측 결과와 종합 판정이 다릅니다.'))
            if not normal and not (record.remarks or '').strip():raise UserError(_('이상 지그의 조치 내용을 기록하십시오.'))
    def action_complete_evidence(self):
        unfinished=self.filtered(lambda r:r.evidence_state!='done')
        result=super().action_complete_evidence()
        for record in unfinished.filtered(lambda r:r.status!='normal'):
            record.jig_id.with_context(**{_CTX:_TOKEN}).write({'use_blocked':True,'blocked_record_id':record.id,
                'blocked_at':fields.Datetime.now(),'state':'inactive'})
        return result


class Attachment(models.Model):
    _inherit='ir.attachment'
    @api.model
    def _cams_evidence_models(self):return super()._cams_evidence_models()+('iatf.jig.record',)
