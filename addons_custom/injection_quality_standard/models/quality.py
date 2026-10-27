import math
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

_SCRAP_TOKEN = object()


class InjectionConditionLimit(models.Model):
    _name = 'injection.condition.limit'
    _description = '사출 품목별 성형조건 기준'
    _inherit = ['mail.thread']
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self:self.env.company)
    product_id = fields.Many2one('product.product', required=True, check_company=True)
    workcenter_id = fields.Many2one('mrp.workcenter', required=True, check_company=True)
    metric = fields.Char('수집 항목 코드', required=True)
    channel_no = fields.Integer('채널', default=0)
    unit = fields.Char('단위', required=True)
    lower = fields.Float('하한', required=True, tracking=True)
    upper = fields.Float('상한', required=True, tracking=True)
    valid_from = fields.Date('적용 시작일', required=True)
    valid_to = fields.Date('적용 종료일')
    document_id = fields.Many2one('iatf.document', string='승인 기준 문서', required=True, check_company=True)
    reason = fields.Text('설정 근거', required=True)
    active = fields.Boolean(default=True)

    def _classify(self, value, unit):
        self.ensure_one()
        if self.unit != unit:
            return '모름: 단위 불일치'
        if self.document_id.state != 'approved':
            return '모름: 기준 문서 승인 확인 필요'
        return '기준 내' if self.lower <= value <= self.upper else '상·하한 이탈'

    @api.constrains('lower','upper','valid_from','valid_to','document_id')
    def _check_limit(self):
        for r in self:
            if not math.isfinite(r.lower) or not math.isfinite(r.upper) or r.lower>r.upper:
                raise ValidationError(_('상·하한을 확인하십시오.'))
            if r.valid_to and r.valid_to<r.valid_from:
                raise ValidationError(_('적용 기간을 확인하십시오.'))
            if r.document_id.state!='approved':
                raise ValidationError(_('승인된 기준 문서를 연결하십시오.'))

    @api.constrains('product_id','workcenter_id','metric','channel_no','valid_from','valid_to','active')
    def _check_overlap(self):
        for r in self.filtered('active'):
            domain=[('id','!=',r.id),('company_id','=',r.company_id.id),('product_id','=',r.product_id.id),
                    ('workcenter_id','=',r.workcenter_id.id),('metric','=',r.metric),('channel_no','=',r.channel_no),
                    ('valid_from','<=',r.valid_to or '9999-12-31'),'|',('valid_to','=',False),('valid_to','>=',r.valid_from)]
            if self.search_count(domain):
                raise ValidationError(_('같은 품목·설비·항목·채널의 적용 기간이 겹칩니다.'))


class InjectionMeasurement(models.Model):
    _inherit = 'injection.machine.shot.measurement'
    condition_status = fields.Char('성형조건 대조', compute='_compute_condition')
    condition_limit_id = fields.Many2one('injection.condition.limit', compute='_compute_condition', string='대조 기준')

    def _compute_condition(self):
        for measurement in self:
            measurement.condition_status='모름: 품번·기준·실측 확인 필요'
            measurement.condition_limit_id=False
            if not self.env['injection.condition.limit'].has_access('read'):
                measurement.condition_status='조회 권한 없음'; continue
            if measurement.value_kind!='actual':
                measurement.condition_status='설정값 (실측 대조 제외)'; continue
            products=self.env['injection.machine.shot.product'].search([('shot_id','=',measurement.shot_id.id)]).product_id
            if len(products)!=1:
                continue
            day=fields.Date.to_date(measurement.shot_id.shot_at)
            limits=self.env['injection.condition.limit'].search([
                ('company_id','=',measurement.shot_id.company_id.id),('product_id','=',products.id),
                ('workcenter_id','=',measurement.shot_id.workcenter_id.id),('metric','=',measurement.metric),
                ('channel_no','=',measurement.channel_no),('valid_from','<=',day),
                '|',('valid_to','=',False),('valid_to','>=',day)])
            if len(limits)!=1:continue
            measurement.condition_limit_id=limits
            measurement.condition_status=limits._classify(measurement.value,measurement.unit)


class StartupStandard(models.Model):
    _name = 'injection.startup.standard'
    _description = '사출 초기 허용불량·폐기 기준'
    _inherit = ['mail.thread']
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self:self.env.company)
    product_id = fields.Many2one('product.product', required=True, check_company=True)
    trigger = fields.Selection([('startup','시업'),('restart','재가동'),('change','조건 변경')], required=True)
    quantity = fields.Float('기준 폐기 수량 (품목 기본단위)', required=True, tracking=True)
    document_id = fields.Many2one('iatf.document', string='T/O·검증 승인 문서', required=True, check_company=True)
    reason = fields.Text('폐기 수량 설정 근거', required=True)
    active = fields.Boolean(default=True)
    @api.constrains('quantity','document_id')
    def _check_basis(self):
        for r in self:
            if not math.isfinite(r.quantity) or r.quantity<=0 or r.document_id.state!='approved':
                raise ValidationError(_('양수 기준 수량과 승인된 검증 문서가 필요합니다.'))


class StartupScrap(models.Model):
    _inherit = 'stock.scrap'
    startup_standard_id = fields.Many2one('injection.startup.standard', string='초기 폐기 기준', check_company=True)
    startup_note = fields.Text('시업·재가동 폐기 근거')
    startup_reference_qty = fields.Float('폐기 처리 시 기준 수량', readonly=True, copy=False)
    startup_basis = fields.Json('폐기 처리 시 기준', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        defaults=self.default_get(['startup_reference_qty','startup_basis'])
        for vals in vals_list:
            if any(vals.get(k,defaults.get(k)) for k in ('startup_reference_qty','startup_basis')):
                raise UserError(_('폐기 기준 스냅샷은 실제 폐기 처리에서 기록합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if {'startup_basis','startup_reference_qty'} & vals.keys() and self.env.context.get('_startup_scrap') is not _SCRAP_TOKEN:
            raise UserError(_('폐기 기준 스냅샷을 직접 수정할 수 없습니다.'))
        if {'startup_standard_id','startup_note'} & vals.keys() and any(r.state=='done' for r in self):
            raise UserError(_('처리한 폐기의 초기 폐기 근거는 수정할 수 없습니다.'))
        return super().write(vals)

    def action_validate(self):
        for scrap in self.filtered('startup_standard_id'):
            standard=scrap.startup_standard_id
            standard.check_access('read')
            if standard.product_id!=scrap.product_id or standard.company_id!=scrap.company_id or not standard.active:
                raise UserError(_('현재 회사·품목의 유효한 초기 폐기 기준을 선택하십시오.'))
            if not (scrap.startup_note or '').strip() or standard.document_id.state!='approved':
                raise UserError(_('폐기 근거와 승인 기준 문서를 확인하십시오.'))
            scrap.with_context(_startup_scrap=_SCRAP_TOKEN).write({'startup_reference_qty':standard.quantity,'startup_basis':{
                'standard_id':standard.id,'quantity':standard.quantity,'product_id':standard.product_id.id,
                'uom_id':standard.product_id.uom_id.id,'trigger':standard.trigger,'document_id':standard.document_id.id,
                'document_revision':standard.document_id.current_revision,'reason':standard.reason}})
        # Preserve existing quality approval, stock moves and quantity guards.
        return super().action_validate()
