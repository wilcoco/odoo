"""Preserve the existing mold ledgers and separate reported development shots."""
from odoo import api,fields,models,_
from odoo.exceptions import UserError,ValidationError
import math

_TEMP_REVISION_TOKEN = object()


class Mold(models.Model):
    _inherit='injection.mold'
    dev_shots=fields.Integer('시사출 보고 타수',compute='_compute_dev_shots',groups='iatf_mold.group_mold_user',
        help='검증 완료된 시사출 보고서의 최신 개정 합계입니다. 현장 current_shots와 자동 합산하거나 차감하지 않습니다.')
    dev_shots_in_counter=fields.Integer('현장 카운터 포함 확인 타수',compute='_compute_dev_shots',groups='iatf_mold.group_mold_user')
    @api.depends('tryout_ids.evidence_state','tryout_ids.evidence_revision','tryout_ids.shot_count','tryout_ids.counter_includes_tryout')
    def _compute_dev_shots(self):
        for mold in self:
            latest={}
            for record in mold.tryout_ids.filtered(lambda row:row.evidence_state=='done'):
                if record.evidence_key not in latest or latest[record.evidence_key].evidence_revision<record.evidence_revision:
                    latest[record.evidence_key]=record
            mold.dev_shots=sum(row.shot_count for row in latest.values())
            mold.dev_shots_in_counter=sum(row.shot_count for row in latest.values() if row.counter_includes_tryout)


class MoldEvidence(models.AbstractModel):
    _name='cams.mold.evidence.mixin'
    _inherit=['cams.evidence.ledger.mixin']
    _description='금형 업무 증빙 공통 검증'
    mold_id=fields.Many2one('injection.mold',ondelete='restrict')
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if record.mold_id.company_id!=record.company_id or not record.product_id or record.product_id!=record.mold_id.product_id:
                raise UserError(_('같은 회사 금형과 실제 적용 품번을 연결하십시오.'))
    def _approval_snapshot(self):
        result=super()._approval_snapshot()
        result['mold_identity']={'id':self.mold_id.id,'code':self.mold_id.code,'product_id':self.mold_id.product_id.id}
        return result


class Tryout(models.Model):
    _name='iatf.mold.tryout'
    _inherit=['cams.mold.evidence.mixin','iatf.mold.tryout']
    record_date=fields.Date(related='tryout_date',store=True,readonly=False,precompute=True,default=None)
    counter_start=fields.Integer('시작 숏카운터')
    counter_end=fields.Integer('종료 숏카운터')
    counter_confirmed=fields.Boolean('실제 카운터 확인')
    counter_includes_tryout=fields.Boolean('현장 누적 카운터에 이번 시사출 포함',
        help='이번 보고 타수가 기존 현장 카운터에 이미 포함되는지 실물 계기와 확인합니다. 값은 카운터를 수정하지 않습니다.')
    production_id=fields.Many2one('mrp.production','연결 생산지시',check_company=True)
    def _evidence_fields(self):
        return super()._evidence_fields() | {'mold_id','tryout_date','tryout_no','reason','shot_count','ok_qty','ng_qty',
            'conclusion','inspection_id','notes','counter_start','counter_end','counter_confirmed','counter_includes_tryout','production_id'}
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if (not record.counter_confirmed or record.counter_start<0 or record.counter_end<=record.counter_start
                or record.shot_count!=record.counter_end-record.counter_start or not record.conclusion or not record.attachment_ids):
                raise UserError(_('실제 시작·종료 카운터와 일치하는 타수·판정·보고서 첨부가 필요합니다.'))
            if record.production_id and (record.production_id.company_id!=record.company_id or record.production_id.product_id!=record.product_id):
                raise UserError(_('생산지시의 회사·품번이 시사출 보고와 다릅니다.'))
            if record.inspection_id and (record.inspection_id.company_id!=record.company_id or record.inspection_id.product_id!=record.product_id
                or record.inspection_id.lot_id!=record.lot_id or record.inspection_id.state not in ('decided','closed')):
                raise UserError(_('연결 초품 검사의 회사·품번·LOT·판정을 확인하십시오.'))
    @api.constrains('shot_count','ok_qty','ng_qty','mold_id')
    def _check_quantities(self):
        for record in self:
            cavities=max(record.mold_id.cavity_count,1)
            if min(record.shot_count,record.ok_qty,record.ng_qty)<0 or record.shot_count and record.ok_qty+record.ng_qty>record.shot_count*cavities:
                raise ValidationError(_('양품·불량 수량은 실제 샷수×금형 캐비티 수 이내여야 합니다.'))


class Maintenance(models.Model):
    _name='iatf.mold.maintenance'
    _inherit=['cams.mold.evidence.mixin','iatf.mold.maintenance']
    _ledger_initial_state='planned'
    company_id=fields.Many2one(related='mold_id.company_id',store=True,readonly=True,precompute=True,default=None)
    record_date=fields.Date(related='date',store=True,readonly=False,precompute=True,default=None)
    cleaning_method=fields.Char('세척 방법')
    cleaning_agent=fields.Char('세척제·조건')
    cleaning_before_photo_ids=fields.Many2many('ir.attachment','mold_clean_before_attachment_rel',string='세척 전 사진')
    cleaning_after_photo_ids=fields.Many2many('ir.attachment','mold_clean_after_attachment_rel',string='세척 후 사진')
    def _bind_owned_uploads(self):
        for record in self:
            extra=(record.cleaning_before_photo_ids | record.cleaning_after_photo_ids)-record.attachment_ids
            if extra:record.write({'attachment_ids':[(4,attachment.id) for attachment in extra]})
        return super()._bind_owned_uploads()
    def write(self,values):
        result=super().write(values)
        if {'cleaning_before_photo_ids','cleaning_after_photo_ids'} & values.keys():self._bind_owned_uploads()
        return result
    def _evidence_fields(self):
        return super()._evidence_fields() | {'mold_id','maintenance_type','date','shots_at_maintenance','work_description',
            'parts_replaced','cost','vendor','duration_hours','result','notes','cleaning_method','cleaning_agent',
            'cleaning_before_photo_ids','cleaning_after_photo_ids'}
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if not record.work_description or not record.result or record.duration_hours<=0:
                raise UserError(_('실제 작업 내용·소요시간·결과를 입력하십시오.'))
            if record.result!='ok' and not record.notes:raise UserError(_('이상 결과의 후속 조치를 기록하십시오.'))
            if record.maintenance_type=='clean' and (not record.cleaning_method or not record.cleaning_agent
                or not record.cleaning_before_photo_ids or not record.cleaning_after_photo_ids):
                raise UserError(_('세척 방법·조건과 전/후 사진을 연결하십시오.'))
            if not (record.cleaning_before_photo_ids | record.cleaning_after_photo_ids) <= record.attachment_ids:
                raise UserError(_('세척 전/후 사진을 증빙 첨부에도 연결하십시오. 승인 후 파일을 보호합니다.'))
    def action_complete_evidence(self):
        fresh=self.filtered(lambda row:row.evidence_state!='done')
        result=super().action_complete_evidence()
        for record in fresh.filtered(lambda row:row.shots_at_maintenance>0):
            record.mold_id.write({'last_pm_shots':record.shots_at_maintenance})
        return result


class MoldTemperatureEvidence(models.Model):
    _name = 'iatf.mold.temp.log'
    _inherit = ['cams.evidence.mixin', 'iatf.mold.temp.log']

    name = fields.Char(default='금형 온도 측정')
    product_id = fields.Many2one(related='mold_id.product_id', store=True, precompute=True, readonly=True)
    responsible_id = fields.Many2one(related='measured_by_id', store=True, precompute=True, readonly=False, default=None)
    company_id = fields.Many2one(related='mold_id.company_id', store=True, precompute=True, readonly=True, default=None)
    action_note = fields.Text('기준 이탈 조치')

    def _evidence_fields(self):
        return super()._evidence_fields() | set(self._MEASUREMENT_FACTS) | {
            'shift', 'production_id', 'measured_by_id', 'notes', 'action_note'}

    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if record.measured_at > fields.Datetime.now():
                raise UserError(_('미래 시각의 측정은 완료할 수 없습니다.'))
            if record.spec_result == 'no_spec':
                raise UserError(_('측정 당시 온도 기준이 없습니다. 실제 승인 기준 확인 후 재측정하십시오.'))
            if record.spec_result == 'ng' and not (record.action_note or '').strip():
                raise UserError(_('온도 이탈에는 후속 조치가 필요합니다. 조치 후에도 원래 부적합 판정은 유지됩니다.'))
            if record.production_id:
                record.production_id.check_access('read')
                if record.production_id.company_id != record.company_id or record.production_id.product_id != record.product_id:
                    raise UserError(_('생산지시의 회사·품번과 측정 금형이 다릅니다.'))

    def _evidence_revision_values(self):
        if self.env.context.get('_temp_revision_token') is not _TEMP_REVISION_TOKEN:
            raise UserError(_('재측정 창에서 실제 측정값을 입력하십시오.'))
        return dict(super()._evidence_revision_values(), **self.env.context['_temp_revision_values'])

    def action_new_evidence_revision(self):
        self.ensure_one()
        if self.env.context.get('_temp_revision_token') is _TEMP_REVISION_TOKEN:
            return super().action_new_evidence_revision()
        if self.evidence_state != 'done':
            raise UserError(_('완료된 측정에서 재측정 개정을 작성하십시오.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'iatf.mold.temp.remeasure',
            'view_mode': 'form', 'target': 'new', 'context': {'default_source_id': self.id}}


class MoldTemperatureRemeasure(models.TransientModel):
    _name = 'iatf.mold.temp.remeasure'
    _description = '금형 온도 재측정 개정'

    source_id = fields.Many2one('iatf.mold.temp.log', required=True, readonly=True)
    temperature = fields.Float('새 실측 온도(℃)', required=True)
    measured_at = fields.Datetime('실제 측정 시각', required=True, default=fields.Datetime.now)
    method = fields.Selection([('ir', '적외선'), ('contact', '접촉식'), ('sensor', '설비센서')], required=True)
    point = fields.Selection([('fixed', '고정측'), ('moving', '이동측')], required=True)
    confirmed = fields.Boolean('실제 재측정값 확인')
    reason = fields.Text('재측정 사유', required=True)

    def action_remeasure(self):
        self.ensure_one()
        self.source_id.check_access('write')
        if (not self.confirmed or not math.isfinite(self.temperature) or not self.reason.strip()
                or self.measured_at > fields.Datetime.now()):
            raise UserError(_('실제 재측정값·시각·사유를 확인하십시오.'))
        return self.source_id.with_context(_temp_revision_token=_TEMP_REVISION_TOKEN,
            _temp_revision_values={'temperature': self.temperature, 'measured_at': self.measured_at,
                'method': self.method, 'point': self.point, 'measured_by_id': self.env.uid,
                'record_date': fields.Datetime.context_timestamp(self, self.measured_at).date(),
                'action_note': False, 'notes': self.reason, 'attachment_ids': [(5, 0, 0)]}
        ).action_new_evidence_revision()


class Attachment(models.Model):
    _inherit='ir.attachment'
    @api.model
    def _cams_evidence_models(self):return super()._cams_evidence_models()+('iatf.mold.tryout','iatf.mold.maintenance','iatf.mold.temp.log')
