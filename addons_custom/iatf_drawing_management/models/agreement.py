from odoo import api,fields,models,_
from odoo.exceptions import UserError

_FIELDS={'quality_drawing_number','quality_drawing_revision','quality_agreement_number','quality_agreement_customer_id',
         'quality_agreement_line_ids','quality_agreement_interval_months'}


class AgreementDocument(models.Model):
    _inherit='iatf.document'
    quality_drawing_number=fields.Char('협정 도면번호',tracking=True)
    quality_drawing_revision=fields.Char('협정 도면개정',tracking=True)
    quality_agreement_number=fields.Char('검사협정 번호',tracking=True)
    quality_agreement_customer_id=fields.Many2one('res.partner','검사협정 고객',tracking=True)
    quality_agreement_interval_months=fields.Integer('확정 대조 주기(개월)',tracking=True)
    quality_agreement_line_ids=fields.One2many('iatf.drawing.agreement.line','document_id','협정 검사항목')
    def _quality_evidence_fields(self):return super()._quality_evidence_fields() | _FIELDS
    def _quality_evidence_snapshot(self):
        result=super()._quality_evidence_snapshot()
        result['agreement_items']=[{key:line[key] for key in ('sequence','name','criterion','output_document','process_name','frequency')}
                                  for line in self.quality_agreement_line_ids.sorted('sequence')]
        return result
    def _check_approval_actor(self):
        super()._check_approval_actor()
        for doc in self.filtered(lambda r:r.quality_evidence_kind=='drawing_agreement'):
            if not all((doc.quality_product_ids,doc.quality_drawing_number,doc.quality_drawing_revision,
                        doc.quality_agreement_number,doc.quality_agreement_customer_id,doc.quality_agreement_line_ids,doc.attachment_ids)):
                raise UserError(_('품번·도면번호/개정·협정번호·고객·검사항목·체결 문서를 기록하십시오.'))
            if doc.quality_agreement_interval_months<=0:
                raise UserError(_('생산기술·품질이 정한 실제 대조 주기를 입력하십시오.'))


class AgreementLine(models.Model):
    _name='iatf.drawing.agreement.line'
    _description='검사협정 항목 (관리문서 원본)'
    _order='sequence,id'
    document_id=fields.Many2one('iatf.document','협정 원본',required=True,ondelete='cascade')
    company_id=fields.Many2one(related='document_id.company_id',store=True)
    sequence=fields.Integer(default=10)
    name=fields.Char('검사항목',required=True)
    criterion=fields.Text('판정 기준',required=True)
    output_document=fields.Char('기록·성적서 양식',required=True)
    process_name=fields.Char('적용 공정',required=True)
    frequency=fields.Char('검사 주기',required=True)
    def _check_draft_documents(self,documents):
        documents._lock_document()
        if any(doc.state!='draft' for doc in documents):raise UserError(_('검토·승인된 협정 항목은 새 문서 개정에서 변경하십시오.'))
    @api.model_create_multi
    def create(self,vals_list):
        ids=[v.get('document_id',self.env.context.get('default_document_id')) for v in vals_list]
        self._check_draft_documents(self.env['iatf.document'].browse([i for i in ids if i]))
        return super().create(vals_list)
    def write(self,values):
        documents=self.document_id
        if values.get('document_id'):documents|=self.env['iatf.document'].browse(values['document_id'])
        self._check_draft_documents(documents)
        return super().write(values)
    def unlink(self):
        self._check_draft_documents(self.document_id)
        return super().unlink()


class DrawingConformity(models.Model):
    _name='iatf.drawing.conformity.check'
    _inherit=['cams.evidence.mixin']
    _description='도면·검사협정 현장 일치성 확인'
    _order='planned_date desc,id desc'
    agreement_document_id=fields.Many2one('iatf.document','승인 검사협정',required=True,ondelete='restrict',domain=[('quality_evidence_kind','=','drawing_agreement')])
    document_ids=fields.Many2many(compute='_compute_documents',store=True)
    planned_date=fields.Date('확인 계획일',required=True)
    checked_date=fields.Date('실제 확인일')
    actual_drawing_number=fields.Char('현장 도면번호')
    actual_revision=fields.Char('현장 도면개정')
    actual_agreement_number=fields.Char('현장 협정번호')
    check_method=fields.Text('대조 방법·확인 항목')
    result=fields.Selection([('pending','미확인'),('match','일치'),('mismatch','불일치')],string='대조 결과',compute='_compute_result')
    action_note=fields.Text('불일치 시 회수·정정 조치')
    @api.depends('agreement_document_id')
    def _compute_documents(self):
        for record in self:record.document_ids=record.agreement_document_id
    @api.depends('checked_date','actual_drawing_number','actual_revision','actual_agreement_number',
        'agreement_document_id.quality_drawing_number','agreement_document_id.quality_drawing_revision',
        'agreement_document_id.quality_agreement_number','evidence_state','completion_snapshot')
    def _compute_result(self):
        for record in self:
            doc=record.agreement_document_id
            record.result=((record.completion_snapshot or {}).get('comparison_result','pending') if record.evidence_state=='done'
                else 'pending' if not record.checked_date or not all((record.actual_drawing_number,record.actual_revision,record.actual_agreement_number))
                else 'match' if record.actual_drawing_number==doc.quality_drawing_number and record.actual_revision==doc.quality_drawing_revision
                and record.actual_agreement_number==doc.quality_agreement_number else 'mismatch')
    def _evidence_calculated_fields(self):return {'result'}
    def _evidence_fields(self):
        return super()._evidence_fields() | {'agreement_document_id','planned_date','checked_date','actual_drawing_number',
            'actual_revision','actual_agreement_number','check_method','action_note'}
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            doc=record.agreement_document_id
            if doc.state!='approved' or not doc.quality_evidence_current or doc.quality_evidence_kind!='drawing_agreement' or record.product_id not in doc.quality_product_ids:
                raise UserError(_('해당 품번의 유효한 승인 검사협정을 선택하십시오.'))
            if not record.checked_date or record.checked_date>fields.Date.context_today(record) or not record.check_method or record.result=='pending':
                raise UserError(_('실제 확인일·현장 도면/협정 번호·개정·대조 방법을 기록하십시오.'))
            if record.result=='mismatch' and not (record.action_note or '').strip():raise UserError(_('불일치 도면·협정의 회수·정정 조치를 기록하십시오.'))
    def _approval_snapshot(self):
        result=super()._approval_snapshot();result['comparison_result']=self.result;return result


class Attachment(models.Model):
    _inherit='ir.attachment'
    @api.model
    def _cams_evidence_models(self):return super()._cams_evidence_models()+('iatf.drawing.conformity.check',)
