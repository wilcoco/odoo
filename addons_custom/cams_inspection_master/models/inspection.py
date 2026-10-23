from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_SAMPLE_FIELDS = {'quality_sample_type','quality_characteristic','quality_criticality','quality_customer_id',
                  'quality_vehicle','quality_plan_year','quality_test_kind','quality_plan_months'}


class Document(models.Model):
    _inherit = 'iatf.document'
    quality_sample_type = fields.Selection([('master','마스터'),('boundary','한도'),('defect','불량'),('appearance','외관')],string='견본 유형',tracking=True)
    quality_characteristic = fields.Text('품질 특성',tracking=True)
    quality_criticality = fields.Char('중요도',tracking=True)
    quality_customer_id = fields.Many2one('res.partner','견본·시험 고객',tracking=True)
    quality_vehicle = fields.Char('차종·적용 사양',tracking=True)
    quality_plan_year = fields.Integer('시험 계획 연도',tracking=True)
    quality_test_kind = fields.Char('시험 종류',tracking=True)
    quality_plan_months = fields.Char('계획 월',help='예: 1,4,7,10. 실제 확정 주기대로 입력하며 타사 참고 주기를 자동 적용하지 않습니다.',tracking=True)

    def _quality_evidence_fields(self):
        return super()._quality_evidence_fields() | _SAMPLE_FIELDS

    @api.constrains('quality_plan_months','quality_plan_year')
    def _check_test_plan(self):
        for document in self:
            if document.quality_plan_year and not 2000 <= document.quality_plan_year <= 2200:
                raise ValidationError(_('계획 연도를 확인하십시오.'))
            if document.quality_plan_months:
                try:months=[int(value.strip()) for value in document.quality_plan_months.split(',')]
                except ValueError:raise ValidationError(_('계획 월은 1~12의 정수를 쉼표로 구분하십시오.'))
                if len(set(months))!=len(months) or any(m<1 or m>12 for m in months):
                    raise ValidationError(_('중복 없이 1~12월을 입력하십시오.'))

    def _check_approval_actor(self):
        super()._check_approval_actor()
        for document in self:
            if document.quality_evidence_kind=='limit_sample' and not all((document.quality_sample_type,document.quality_characteristic,document.quality_customer_id)):
                raise UserError(_('한도견본 유형·품질 특성·고객을 입력하십시오.'))
            if document.quality_evidence_kind=='reliability_plan' and not all((document.quality_plan_year,document.quality_test_kind,document.quality_plan_months)):
                raise UserError(_('시험 계획의 연도·종류·계획 월을 입력하십시오.'))


class LimitSampleCheck(models.Model):
    _name = 'cams.limit.sample.check'
    _description = '한도견본 점검 이력'
    _inherit = ['cams.evidence.mixin']
    _order = 'record_date desc,id desc'
    sample_document_id = fields.Many2one('iatf.document','한도견본 원본',required=True,ondelete='restrict',domain=[('quality_evidence_kind','=','limit_sample')])
    document_ids = fields.Many2many(compute='_compute_documents',store=True)
    result = fields.Selection([('ok','유효·이상 없음'),('ng','교체·개정 필요')],string='점검 결과',required=True)
    check_detail = fields.Text('외관·식별·유효기간 확인',required=True)
    action_note = fields.Text('이상 조치')

    @api.depends('sample_document_id')
    def _compute_documents(self):
        for record in self:record.document_ids=record.sample_document_id

    def _evidence_fields(self):
        return super()._evidence_fields() | {'sample_document_id','result','check_detail','action_note'}

    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            document=record.sample_document_id
            if document.quality_evidence_kind!='limit_sample' or document.state!='approved':
                raise UserError(_('승인된 한도견본 원본을 선택하십시오.'))
            if record.product_id not in document.quality_product_ids:
                raise UserError(_('견본 적용 품번과 점검 품번이 다릅니다.'))
            if record.result=='ok' and (not document.quality_evidence_current or not document.quality_valid_until or document.quality_valid_until < record.record_date):
                raise UserError(_('만료·회수된 견본을 유효로 점검 완료할 수 없습니다.'))
            if record.result=='ng' and not (record.action_note or '').strip():
                raise UserError(_('이상 결과에는 교체·개정 조치를 기록하십시오.'))
            approvers=record.approval_request_id.line_ids.user_id
            if len(approvers)<2 or record.responsible_id in approvers:
                raise UserError(_('담당자와 다른 두 명의 확인자를 결재선에 지정하십시오.'))


class PeriodicTest(models.Model):
    _name = 'cams.periodic.test'
    _description = '정기·신뢰성 시험 계획 대비 실적'
    _inherit = ['cams.evidence.mixin']
    _order = 'planned_date, id'
    plan_document_id = fields.Many2one('iatf.document','승인 시험 계획',required=True,ondelete='restrict',domain=[('quality_evidence_kind','=','reliability_plan')])
    document_ids = fields.Many2many(compute='_compute_documents',store=True)
    planned_date = fields.Date('계획일',required=True)
    actual_date = fields.Date('시험일')
    sample_count = fields.Integer('시료 수')
    result = fields.Selection([('pending','미실시'),('pass','적합'),('fail','부적합')],default='pending',string='시험 결과',required=True)
    result_note = fields.Text('판정 근거·이상 조치')

    @api.depends('plan_document_id')
    def _compute_documents(self):
        for record in self:record.document_ids=record.plan_document_id

    def _evidence_fields(self):
        return super()._evidence_fields() | {'plan_document_id','planned_date','actual_date','sample_count','result','result_note'}

    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            document=record.plan_document_id
            if document.state!='approved' or document.quality_evidence_kind!='reliability_plan':
                raise UserError(_('승인 시험 계획을 선택하십시오.'))
            months={int(value.strip()) for value in (document.quality_plan_months or '').split(',') if value.strip()}
            if record.planned_date.year!=document.quality_plan_year or record.planned_date.month not in months:
                raise UserError(_('승인된 연도·계획 월과 시험 계획일이 다릅니다.'))
            if record.product_id not in document.quality_product_ids or not record.lot_id:
                raise UserError(_('계획 적용 품번과 제조 LOT를 연결하십시오.'))
            if (not record.actual_date or record.actual_date > fields.Date.context_today(record) or record.sample_count<=0
                    or record.result=='pending' or not record.attachment_ids or not (record.result_note or '').strip()):
                raise UserError(_('실제 시험일·시료 수·결과·성적서·판정 근거가 있어야 완료 결재할 수 있습니다.'))


class Attachment(models.Model):
    _inherit = 'ir.attachment'
    @api.model
    def _cams_evidence_models(self):
        return super()._cams_evidence_models()+('cams.limit.sample.check','cams.periodic.test')
