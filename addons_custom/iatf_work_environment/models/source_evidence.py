"""Source links on the existing check-sheet framework, not a second SQ ledger."""
from odoo import api,fields,models,_
from odoo.exceptions import AccessError,UserError
from odoo.addons.iatf_document_control.models.inspection_evidence import validate_inspection_links,inspection_documents_snapshot,_lock

_PURPOSES=[('general','일반 점검'),('lighting','조도·측정 위치'),('foolproof','F/PROOF'),
           ('rework','재작업 확인'),('five_s','5S·구역 확인'),('fifo','보관·선입선출')]
_SOURCE_FIELDS={'lot_id','workcenter_id','production_id','document_ids','attachment_ids','trace_exception'}


class LayoutDocument(models.Model):
    _inherit='iatf.document'
    quality_evidence_kind=fields.Selection(selection_add=[('work_area_layout','작업장·보관장 배치도')],ondelete={'work_area_layout':'set null'})


class SheetSource(models.Model):
    _inherit='iatf.check.sheet'
    quality_purpose=fields.Selection(_PURPOSES,string='점검 용도',default='general',required=True,tracking=True)
    layout_document_id=fields.Many2one('iatf.document','승인 배치도·측정 위치도',ondelete='restrict')
    def _source_policy_actor(self):
        if not self.env.su and not self.env.user.has_group('iatf_work_environment.group_work_environment_manager'):
            raise AccessError(_('점검 용도와 배치도 연결은 작업환경 책임자가 관리합니다.'))
    @api.model_create_multi
    def create(self,vals_list):
        if any(key in values or 'default_'+key in self.env.context for values in vals_list for key in ('quality_purpose','layout_document_id')):
            self._source_policy_actor()
        return super().create(vals_list)
    def write(self,values):
        touched={'quality_purpose','layout_document_id'} & values.keys()
        if touched:self._source_policy_actor()
        result=super().write(values)
        if touched:self._log_revision(_('점검 용도 또는 승인 배치도 변경'))
        return result


class CheckSource(models.Model):
    _inherit='iatf.check.record'
    quality_purpose=fields.Selection(_PURPOSES,string='기록 생성 시 점검 용도',readonly=True,copy=False)
    lot_id=fields.Many2one('stock.lot','생산·원재료 LOT',check_company=True)
    workcenter_id=fields.Many2one('mrp.workcenter','설비·작업장',check_company=True)
    production_id=fields.Many2one('mrp.production','생산지시',check_company=True)
    document_ids=fields.Many2many('iatf.document',string='배치도·근거 문서')
    attachment_ids=fields.Many2many('ir.attachment',string='측정·현장 사진')
    trace_exception=fields.Text('LOT·설비 해당없음 근거')

    @api.model_create_multi
    def create(self,vals_list):
        prepared=[]
        for values in vals_list:
            values=dict(values)
            if 'quality_purpose' in values or 'default_quality_purpose' in self.env.context:
                raise UserError(_('점검 용도는 선택한 점검 시트에서 가져옵니다.'))
            sheet=self.env['iatf.check.sheet'].browse(values.get('sheet_id',self.env.context.get('default_sheet_id')))
            sheet.check_access('read')
            values['quality_purpose']=sheet.quality_purpose or 'general'
            if sheet.layout_document_id and 'document_ids' not in values:values['document_ids']=[(4,sheet.layout_document_id.id)]
            prepared.append(values)
        records=super().create(prepared)
        records._bind_source_uploads()
        return records

    def write(self,values):
        if 'quality_purpose' in values:raise UserError(_('기록 용도는 직접 바꾸지 않습니다.'))
        if 'sheet_id' in values and any(row.quality_purpose not in (False,'general') for row in self):
            raise UserError(_('용도가 지정된 점검은 기존 시트를 유지하고 새 기록을 작성하십시오.'))
        result=super().write(values)
        if 'attachment_ids' in values:self._bind_source_uploads()
        return result

    def _bind_source_uploads(self):
        for record in self:
            uploads=record.attachment_ids.filtered(lambda a:a.create_uid==self.env.user and not a.res_model and not a.res_id)
            if uploads:uploads.write({'res_model':record._name,'res_id':record.id})

    @api.constrains('state','quality_purpose','lot_id','workcenter_id','production_id','document_ids','attachment_ids','trace_exception')
    def _check_quality_sources(self):
        validate_inspection_links(self)
        for record in self:
            for source in (record.lot_id,record.workcenter_id,record.production_id):
                if source:source.check_access('read')
                if source and source.company_id!=record.company_id:raise UserError(_('점검과 원천 자료의 회사가 다릅니다.'))
            if record.production_id and record.lot_id and record.production_id.product_id!=record.lot_id.product_id:
                raise UserError(_('생산지시와 LOT의 품번이 다릅니다.'))
            if record.state!='done' or record.quality_purpose in (False,'general'):continue
            if not record.checker_id or record.check_date>fields.Date.context_today(record):
                raise UserError(_('실제 점검일과 담당자를 확인하십시오.'))
            if (not record.lot_id or not record.workcenter_id) and not (record.trace_exception or '').strip():
                raise UserError(_('LOT·설비를 연결하거나 구역 점검 등 실제 해당없음 사유를 입력하십시오.'))
            if record.quality_purpose=='lighting':
                layout=record.document_ids.filtered(lambda d:d.quality_evidence_kind=='work_area_layout' and d.state=='approved' and d.quality_evidence_current)
                if not layout or record.sheet_id.layout_document_id not in layout or record.sheet_id.cycle!='monthly':
                    raise UserError(_('조도 점검은 승인 측정 위치도와 월간 점검 시트를 사용하십시오.'))
                if any(line.entry_type!='numeric' or not line._has_spec() or (line.uom_name or '').lower() not in ('lux','lx') for line in record.line_ids):
                    raise UserError(_('배치도 위치별 확정 조도 기준(Lux)을 등록하십시오. 미정 기준으로 적합 완료하지 않습니다.'))
            if record._derive_overall()[1] and not record.corrective_action:
                raise UserError(_('이상 항목의 조치 내용을 기록하십시오.'))

    def _snapshot_values(self):
        result=super()._snapshot_values()
        self._check_quality_sources()
        result['source_context']={'purpose':self.quality_purpose,'lot_id':self.lot_id.id,
            'lot_name':self.lot_id.name,'workcenter_id':self.workcenter_id.id,'workcenter_name':self.workcenter_id.name,
            'production_id':self.production_id.id,'production_name':self.production_id.name,
            'trace_exception':self.trace_exception,'references':inspection_documents_snapshot(self)}
        result['source_attachment_ids']=[(6,0,(self.attachment_ids | self.document_ids.attachment_ids).ids)]
        return result


class CheckSnapshot(models.Model):
    _inherit='iatf.check.record.snapshot'
    source_context=fields.Json('완료 당시 LOT·설비·배치도',readonly=True)
    source_attachment_ids=fields.Many2many('ir.attachment','check_snapshot_source_attachment_rel',string='완료 당시 파일',readonly=True)


class Attachment(models.Model):
    _inherit='ir.attachment'
    def _check_work_environment_evidence(self):
        records=self.env['iatf.check.record'].sudo().search([('attachment_ids','in',self.ids),('was_done','=',True)])
        snapshots=self.env['iatf.check.record.snapshot'].sudo().search([('source_attachment_ids','in',self.ids)])
        if records or snapshots:
            _lock(records)
            _lock(snapshots)
            raise UserError(_('점검 완료 당시 첨부는 변경하지 않습니다. 정정 차수에 새 파일을 연결하십시오.'))
    def write(self,values):
        if {'datas','raw','db_datas','store_fname','name','mimetype','type','url','res_model','res_id','public','company_id'} & values.keys():self._check_work_environment_evidence()
        return super().write(values)
    def unlink(self):
        self._check_work_environment_evidence()
        return super().unlink()
