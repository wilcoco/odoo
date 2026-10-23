"""Material evidence lives beside existing equipment and traceability ledgers."""
from odoo import api,fields,models,_
from odoo.exceptions import UserError,ValidationError

_CRITERIA={'quality_material_process','quality_limits_confirmed','quality_limit_source',
    'quality_dry_temp_min','quality_dry_temp_max','quality_dry_hours','quality_prestart_hours',
    'quality_moisture_in_ppm','quality_moisture_before_ppm','quality_moisture_method',
    'quality_grind_good_mm','quality_grind_reject_mm','quality_grind_sample_ml',
    'quality_blade_gap_mm','quality_blade_change_kg'}


class MaterialDocument(models.Model):
    _inherit='iatf.document'
    quality_material_process=fields.Selection([('dryer','수지 건조'),('grinder','분쇄')],string='설비 기준 공정',tracking=True)
    quality_limits_confirmed=fields.Boolean('에스콘 실제 기준값 확인',tracking=True,
        help='타사 참고 수치를 그대로 승인하지 않습니다. 생산기술·품질이 확인한 값과 출처를 기록하십시오.')
    quality_limit_source=fields.Text('기준값 확인 근거',tracking=True)
    quality_dry_temp_min=fields.Float('건조 온도 하한(℃)',tracking=True)
    quality_dry_temp_max=fields.Float('건조 온도 상한(℃)',tracking=True)
    quality_dry_hours=fields.Float('최소 건조 시간(h)',tracking=True)
    quality_prestart_hours=fields.Float('조업 전 최소 가동(h)',tracking=True)
    quality_moisture_in_ppm=fields.Float('입고 수분 한계(PPM)',tracking=True)
    quality_moisture_before_ppm=fields.Float('성형 전 수분 한계(PPM)',tracking=True)
    quality_moisture_method=fields.Text('수분 채취 위치·측정법',tracking=True)
    quality_grind_good_mm=fields.Float('사용 가능 입자 상한(mm)',tracking=True)
    quality_grind_reject_mm=fields.Float('사용 불가 입자 하한(mm)',tracking=True)
    quality_grind_sample_ml=fields.Float('분쇄 샘플 용량(mL)',tracking=True)
    quality_blade_gap_mm=fields.Float('칼날 간격 한계(mm)',tracking=True)
    quality_blade_change_kg=fields.Float('칼날 교환 누적 분쇄량(kg)',tracking=True)

    def _quality_evidence_fields(self):return super()._quality_evidence_fields() | _CRITERIA

    def _check_approval_actor(self):
        super()._check_approval_actor()
        for doc in self.filtered('quality_material_process'):
            if doc.quality_evidence_kind!='equipment_standard' or not doc.quality_limits_confirmed or not (doc.quality_limit_source or '').strip() or not doc.quality_product_ids:
                raise UserError(_('설비 기준 용도·적용 자재·실제 기준값 확인·근거를 입력하십시오.'))
            if doc.quality_material_process=='dryer' and (
                doc.quality_dry_temp_min<0 or doc.quality_dry_temp_max<=doc.quality_dry_temp_min or doc.quality_dry_hours<=0
                or doc.quality_prestart_hours<0 or doc.quality_moisture_in_ppm<=0 or doc.quality_moisture_before_ppm<=0
                or not (doc.quality_moisture_method or '').strip()):
                raise UserError(_('온도 범위·최소 시간·수분 한계·채취 위치와 측정법을 확인하십시오.'))
            if doc.quality_material_process=='grinder' and (
                doc.quality_grind_good_mm<=0 or doc.quality_grind_reject_mm<=doc.quality_grind_good_mm
                or doc.quality_grind_sample_ml<=0 or doc.quality_blade_gap_mm<=0 or doc.quality_blade_change_kg<=0):
                raise UserError(_('입자 등급 경계·샘플 용량·칼날 간격·교환 기준을 확인하십시오.'))


class MaterialEvidence(models.AbstractModel):
    _name='cams.material.evidence.mixin'
    _inherit=['cams.evidence.mixin']
    _description='자재 설비 원천 기준 연결'
    equipment_id=fields.Many2one('iatf.equipment','원천 설비',check_company=True,ondelete='restrict',required=True)
    standard_document_id=fields.Many2one('iatf.document','승인 설비 기준',required=True,ondelete='restrict',domain=[('quality_evidence_kind','=','equipment_standard')])
    document_ids=fields.Many2many(compute='_compute_documents',store=True)
    shift=fields.Selection([('day','주간'),('night','야간')],string='교대',required=True)
    action_note=fields.Text('이상 조치·사용 제한')

    @api.depends('standard_document_id')
    def _compute_documents(self):
        for record in self:record.document_ids=record.standard_document_id

    def _evidence_fields(self):return super()._evidence_fields() | {'equipment_id','standard_document_id','shift','action_note'}

    def _material_process(self):return False

    def _evidence_derived(self):return {}

    def _approval_snapshot(self):
        result=super()._approval_snapshot()
        result['derived']=self._evidence_derived()
        return result

    def _completed_derived(self):
        self.ensure_one()
        return (self.completion_snapshot or {}).get('derived',{}) if self.evidence_state=='done' else None

    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            document=record.standard_document_id
            if (document.state!='approved' or not document.quality_evidence_current
                or document.quality_evidence_kind!='equipment_standard' or document.quality_material_process!=record._material_process()
                or not document.quality_limits_confirmed or record.product_id not in document.quality_product_ids):
                raise UserError(_('이 자재·공정에 맞는 유효한 승인 기준을 선택하십시오.'))
            if record.equipment_id.company_id and record.equipment_id.company_id!=record.company_id:
                raise UserError(_('설비와 기록의 회사가 다릅니다.'))
            if record.equipment_id.workcenter_id and record.equipment_id.workcenter_id!=record.workcenter_id:
                raise UserError(_('설비 대장의 작업장과 점검 작업장이 다릅니다.'))


class DryerCheck(models.Model):
    _name='cams.dryer.check'
    _inherit=['cams.material.evidence.mixin']
    _description='건조장치 일상·용량·수분 점검'
    _order='record_date desc,id desc'
    temperature=fields.Float('실측 온도(℃)')
    remaining_kg=fields.Float('실측 잔량(kg)')
    hourly_usage_kg=fields.Float('시간당 사용량(kg/h)')
    capacity_kg=fields.Float('건조기 용량(kg)')
    shot_weight_g=fields.Float('샷 중량(g)')
    cycle_seconds=fields.Float('사이클(s)')
    calculated_usage_kg=fields.Float('샷·사이클 계산 사용량(kg/h)',compute='_compute_dryer')
    lower_level_kg=fields.Float('건조 시간 기준 하한선(kg)',compute='_compute_dryer')
    dryer_started_at=fields.Datetime('건조 가동 시각')
    production_started_at=fields.Datetime('조업 시작 시각')
    moisture_in_ppm=fields.Float('입고 수분(PPM)')
    moisture_1h_ppm=fields.Float('1시간 후 수분(PPM)')
    moisture_2h_ppm=fields.Float('2시간 후 수분(PPM)')
    moisture_3h_ppm=fields.Float('3시간 후 수분(PPM)')
    moisture_before_ppm=fields.Float('성형 전 수분(PPM)')
    measurement_method=fields.Text('실제 채취 위치·측정법')
    measurement_reference=fields.Char('측정기 출력·수신 자료 식별번호')
    measurements_confirmed=fields.Boolean('실측값 입력 확인',help='미측정 값을 0으로 간주하지 않습니다. 실제 측정한 값만 확인하십시오.')
    filter_result=fields.Selection([('ok','이상 없음'),('ng','청소·교환 필요')],string='필터 점검')
    result=fields.Selection([('pending','미확인'),('ok','기준 이내'),('ng','기준 이탈')],string='계산 판정',compute='_compute_dryer')

    def _material_process(self):return 'dryer'

    def _evidence_calculated_fields(self):return {'result','lower_level_kg','calculated_usage_kg'}

    def _evidence_derived(self):
        return {key:self[key] for key in ('result','lower_level_kg','calculated_usage_kg')}

    def _evidence_fields(self):
        return super()._evidence_fields() | {'temperature','remaining_kg','hourly_usage_kg','capacity_kg','shot_weight_g','cycle_seconds',
            'dryer_started_at','production_started_at','moisture_in_ppm','moisture_1h_ppm','moisture_2h_ppm','moisture_3h_ppm',
            'moisture_before_ppm','measurement_method','measurement_reference','measurements_confirmed','filter_result'}

    @api.depends('evidence_state','completion_snapshot','temperature','remaining_kg','hourly_usage_kg','capacity_kg','shot_weight_g','cycle_seconds',
        'dryer_started_at','production_started_at','moisture_in_ppm','moisture_before_ppm','measurements_confirmed','filter_result',
        'standard_document_id.quality_dry_hours','standard_document_id.quality_prestart_hours',
        'standard_document_id.quality_dry_temp_min','standard_document_id.quality_dry_temp_max',
        'standard_document_id.quality_moisture_in_ppm','standard_document_id.quality_moisture_before_ppm')
    def _compute_dryer(self):
        for record in self:
            completed=record._completed_derived()
            if completed is not None:
                record.result=completed.get('result','pending')
                record.lower_level_kg=completed.get('lower_level_kg',0)
                record.calculated_usage_kg=completed.get('calculated_usage_kg',0)
                continue
            doc=record.standard_document_id
            record.calculated_usage_kg=record.shot_weight_g*3.6/record.cycle_seconds if record.cycle_seconds>0 else 0
            record.lower_level_kg=doc.quality_dry_hours*record.hourly_usage_kg
            hours=(record.production_started_at-record.dryer_started_at).total_seconds()/3600 if record.production_started_at and record.dryer_started_at else -1
            if not record.measurements_confirmed or not record.filter_result or not doc.quality_limits_confirmed:
                record.result='pending'
            else:
                record.result='ok' if (doc.quality_dry_temp_min<=record.temperature<=doc.quality_dry_temp_max
                    and record.lower_level_kg<=record.remaining_kg<=record.capacity_kg
                    and hours>=max(doc.quality_dry_hours,doc.quality_prestart_hours)
                    and record.moisture_in_ppm<=doc.quality_moisture_in_ppm
                    and record.moisture_before_ppm<=doc.quality_moisture_before_ppm and record.filter_result=='ok') else 'ng'

    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if (not record.lot_id or not record.measurements_confirmed or not record.filter_result
                or record.hourly_usage_kg<=0 or record.capacity_kg<=0 or not record.measurement_method
                or not record.dryer_started_at or not record.production_started_at
                or record.production_started_at>fields.Datetime.now() or record.production_started_at<record.dryer_started_at):
                raise UserError(_('실제 LOT·온도·잔량·사용량·가동 시각·수분 측정·필터 결과를 기록하십시오.'))
            if any(record[name]<0 for name in ('remaining_kg','moisture_in_ppm','moisture_1h_ppm','moisture_2h_ppm','moisture_3h_ppm','moisture_before_ppm')):
                raise UserError(_('잔량·수분 측정값은 음수일 수 없습니다.'))
            if record.result=='ng' and not (record.action_note or '').strip():
                raise UserError(_('건조 기준 이탈에는 사용 제한과 조치를 기록하십시오.'))


class DryerFilterLog(models.Model):
    _name='cams.dryer.filter.log'
    _inherit=['cams.material.evidence.mixin']
    _description='건조기 필터 청소·교환 이력'
    operation=fields.Selection([('clean','청소'),('replace','교환')],string='작업',required=True)
    completed_detail=fields.Text('작업 결과',required=True)
    next_due_date=fields.Date('기준에 따른 차기 예정일')
    def _material_process(self):return 'dryer'
    def _evidence_fields(self):return super()._evidence_fields() | {'operation','completed_detail','next_due_date'}
    def _evidence_validate(self):
        super()._evidence_validate()
        if any(r.next_due_date and r.next_due_date<=r.record_date for r in self):
            raise UserError(_('차기 예정일은 실제 작업일 이후로 입력하십시오.'))


class GrindSample(models.Model):
    _name='cams.grind.sample'
    _inherit=['cams.material.evidence.mixin']
    _description='월간 분쇄재 입자 샘플 점검'
    sample_volume_ml=fields.Float('샘플 용량(mL)',required=True)
    maximum_particle_mm=fields.Float('최대 입자(mm)',required=True)
    measurements_confirmed=fields.Boolean('실측값 입력 확인')
    regrind_log_id=fields.Many2one('iatf.regrind.log','분쇄일지',ondelete='restrict',required=True)
    result=fields.Selection([('pending','미확인'),('usable','사용 가능'),('inspect','상세 검사'),('reject','사용 불가')],compute='_compute_result',string='입자 판정')
    def _material_process(self):return 'grinder'
    def _evidence_calculated_fields(self):return {'result'}
    def _evidence_derived(self):return {'result':self.result}
    def _evidence_fields(self):return super()._evidence_fields() | {'sample_volume_ml','maximum_particle_mm','measurements_confirmed','regrind_log_id'}
    @api.depends('evidence_state','completion_snapshot','maximum_particle_mm','measurements_confirmed','standard_document_id.quality_grind_good_mm','standard_document_id.quality_grind_reject_mm')
    def _compute_result(self):
        for record in self:
            completed=record._completed_derived()
            if completed is not None:
                record.result=completed.get('result','pending');continue
            doc=record.standard_document_id
            record.result=('pending' if not record.measurements_confirmed or not doc.quality_limits_confirmed
                else 'usable' if record.maximum_particle_mm<=doc.quality_grind_good_mm
                else 'reject' if record.maximum_particle_mm>=doc.quality_grind_reject_mm else 'inspect')
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            source=record.regrind_log_id
            source.check_access('read')
            if (not record.measurements_confirmed or record.maximum_particle_mm<=0
                or record.sample_volume_ml<record.standard_document_id.quality_grind_sample_ml
                or not record.lot_id or source.output_lot_id!=record.lot_id or source.company_id!=record.company_id):
                raise UserError(_('실제 샘플 용량·최대 입자·분쇄 산출 LOT·회사를 확인하십시오.'))
            if record.result!='usable' and not (record.action_note or '').strip():
                raise UserError(_('상세 검사·사용 불가에는 격리·검사 조치를 기록하십시오.'))


class GrinderCheck(models.Model):
    _name='cams.grinder.check'
    _inherit=['cams.material.evidence.mixin']
    _description='분쇄기 점검 일지'
    blade_gap_mm=fields.Float('실측 칼날 간격(mm)')
    ground_since_change_kg=fields.Float('교환 후 누적 분쇄량(kg)')
    measurements_confirmed=fields.Boolean('실측값 입력 확인')
    cleanliness=fields.Selection([('ok','청결'),('ng','청소 필요')],string='청결')
    foreign_material=fields.Selection([('ok','이물 없음'),('ng','이물 발견')],string='이물')
    gear_oil=fields.Selection([('ok','정상'),('ng','보충·교환 필요')],string='기어오일')
    result=fields.Selection([('pending','미확인'),('ok','기준 이내'),('ng','조치 필요')],compute='_compute_result',string='점검 판정')
    def _material_process(self):return 'grinder'
    def _evidence_calculated_fields(self):return {'result'}
    def _evidence_derived(self):return {'result':self.result}
    def _evidence_fields(self):return super()._evidence_fields() | {'blade_gap_mm','ground_since_change_kg','measurements_confirmed','cleanliness','foreign_material','gear_oil'}
    @api.depends('evidence_state','completion_snapshot','blade_gap_mm','ground_since_change_kg','measurements_confirmed','cleanliness','foreign_material','gear_oil',
        'standard_document_id.quality_blade_gap_mm','standard_document_id.quality_blade_change_kg')
    def _compute_result(self):
        for record in self:
            completed=record._completed_derived()
            if completed is not None:
                record.result=completed.get('result','pending');continue
            doc=record.standard_document_id
            record.result=('pending' if not record.measurements_confirmed or not all((record.cleanliness,record.foreign_material,record.gear_oil))
                else 'ok' if 0<=record.blade_gap_mm<=doc.quality_blade_gap_mm and 0<=record.ground_since_change_kg<doc.quality_blade_change_kg
                    and record.cleanliness==record.foreign_material==record.gear_oil=='ok' else 'ng')
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if record.result=='pending':raise UserError(_('분쇄기 점검값을 실제 측정하고 확인하십시오.'))
            if record.result=='ng' and not (record.action_note or '').strip():raise UserError(_('분쇄기 이상에는 조치를 기록하십시오.'))


class Attachment(models.Model):
    _inherit='ir.attachment'
    @api.model
    def _cams_evidence_models(self):
        return super()._cams_evidence_models()+('cams.dryer.check','cams.dryer.filter.log','cams.grind.sample','cams.grinder.check')
