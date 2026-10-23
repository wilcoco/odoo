"""Immutable completion on existing IATF approval, without a second SQ ledger."""
import hashlib
import math
import uuid
from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.iatf_document_control.models.inspection_evidence import (
    validate_inspection_links, inspection_documents_snapshot)

_TOKEN = object()
_CTX = '_cams_evidence_transition'
_PROTECTED = {'evidence_key','evidence_revision','previous_evidence_id','evidence_state',
              'completion_snapshot','completed_by_id','completed_at'}


class Evidence(models.AbstractModel):
    _name = 'cams.evidence.mixin'
    _description = '제조품질 증빙 개정·완료 기록'
    _inherit = ['iatf.approval.mixin']
    _check_company_auto = True

    name = fields.Char('기록명',required=True,tracking=True)
    company_id = fields.Many2one('res.company','회사',required=True,default=lambda s:s.env.company,index=True)
    record_date = fields.Date('기록일',required=True,default=fields.Date.context_today,tracking=True)
    responsible_id = fields.Many2one('res.users','담당자',required=True,default=lambda s:s.env.user,tracking=True)
    product_id = fields.Many2one('product.product','품번',check_company=True)
    lot_id = fields.Many2one('stock.lot','원천 LOT',check_company=True)
    workcenter_id = fields.Many2one('mrp.workcenter','원천 작업장·설비',check_company=True)
    trace_exception = fields.Text('LOT·설비가 해당하지 않는 근거',help='양산 전 원청 견본, 별도 시험실 등 실제 사유만 기록합니다.')
    document_ids = fields.Many2many('iatf.document',string='기준·근거 문서')
    attachment_ids = fields.Many2many('ir.attachment',string='사진·성적서')
    note = fields.Text('비고')
    evidence_key = fields.Char(readonly=True,copy=False,default=lambda s:uuid.uuid4().hex,index=True)
    evidence_revision = fields.Integer('개정 차수',readonly=True,copy=False,default=1)
    previous_evidence_id = fields.Integer('이전 개정 ID',readonly=True,copy=False)
    evidence_state = fields.Selection([('draft','작성·결재'),('done','검증 완료')],string='기록 상태',default='draft',readonly=True,copy=False,tracking=True)
    completion_snapshot = fields.Json('완료 당시 기록',readonly=True,copy=False)
    completed_by_id = fields.Many2one('res.users','완료 확인자',readonly=True,copy=False)
    completed_at = fields.Datetime('완료 확인 시각',readonly=True,copy=False)
    _sql_constraints = [('evidence_revision_unique','unique(company_id,evidence_key,evidence_revision)','같은 기록의 개정 차수는 중복될 수 없습니다.')]

    def _evidence_fields(self):
        return {'name','company_id','record_date','responsible_id','product_id','lot_id',
                'workcenter_id','trace_exception','document_ids','attachment_ids','note'}

    def _approval_reset_ignored_fields(self):
        return super()._approval_reset_ignored_fields() | _PROTECTED

    def _evidence_internal(self):
        return self.env.context.get(_CTX) is _TOKEN

    def _evidence_calculated_fields(self):
        return set()

    @api.model_create_multi
    def create(self, vals_list):
        if not self._evidence_internal():
            for values in vals_list:
                if any(key in values or 'default_'+key in self.env.context for key in _PROTECTED | self._evidence_calculated_fields()):
                    raise UserError(_('개정·완료 근거는 전용 절차에서만 기록합니다.'))
        records = super().create(vals_list)
        records._bind_owned_uploads()
        return records

    def _bind_owned_uploads(self):
        # Odoo uploads a binary before a new form has its final record id. Bind
        # only the current user's unbound uploads, never somebody else's file.
        for record in self:
            uploads = record.attachment_ids.filtered(lambda a:
                a.create_uid == self.env.user and not a.res_model and not a.res_id)
            if uploads:
                uploads.write({'res_model':record._name,'res_id':record.id})

    def write(self, values):
        if not self._evidence_internal():
            if (_PROTECTED | self._evidence_calculated_fields()) & values.keys():
                raise UserError(_('완료·개정 결과를 직접 변경할 수 없습니다.'))
            if self._evidence_fields() & values.keys():
                self._approval_lock()
                if any(r.evidence_state=='done' or r.approval_state in ('in_progress','approved') for r in self):
                    raise UserError(_('상신·승인·완료된 내용은 고치지 않습니다. 반려 후 수정하거나 새 개정을 만드십시오.'))
        result = super().write(values)
        if 'attachment_ids' in values:
            self._bind_owned_uploads()
        return result

    def unlink(self):
        self._approval_lock()
        if any(r.evidence_state=='done' for r in self):
            raise UserError(_('완료된 증빙은 삭제할 수 없습니다.'))
        return super().unlink()

    @api.constrains('company_id','responsible_id','lot_id','product_id','document_ids','attachment_ids')
    def _check_evidence_scope(self):
        validate_inspection_links(self)
        for record in self:
            if record.company_id not in record.responsible_id.company_ids or record.responsible_id.share:
                raise ValidationError(_('담당자는 같은 회사의 내부 사용자여야 합니다.'))
            if record.lot_id and record.lot_id.product_id != record.product_id:
                raise ValidationError(_('원천 LOT와 품번이 다릅니다.'))

    def _evidence_validate(self):
        for record in self:
            if record.evidence_state!='draft':
                raise UserError(_('완료된 기록은 다시 상신하지 않습니다.'))
            if not record.responsible_id.active or record.record_date > fields.Date.context_today(record):
                raise UserError(_('활성 담당자와 실제 기록일을 확인하십시오.'))
            if (not record.lot_id or not record.workcenter_id) and not (record.trace_exception or '').strip():
                raise UserError(_('원천 LOT·작업장을 연결하거나 실제 해당없음 근거를 입력하십시오.'))
            if any(record._fields[name].type=='float' and not math.isfinite(record[name]) for name in record._evidence_fields()):
                raise UserError(_('측정값에는 유한한 수를 입력하십시오.'))
        self._check_evidence_scope()

    def _approval_snapshot(self):
        self.ensure_one()
        data={}
        for name in sorted(self._evidence_fields()):
            field=self._fields[name];value=self[name]
            if field.type=='binary':
                data[name]={'sha256':hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()} if value else False
            else:
                data[name]=value.ids if field.relational else fields.Date.to_string(value) if field.type=='date' else fields.Datetime.to_string(value) if field.type=='datetime' else value
        references = inspection_documents_snapshot(self)
        # The base document fingerprint intentionally excludes optional business
        # extensions. Capture their actual controlled values for this workflow.
        quality = {}
        self.document_ids.check_access('read')
        for document in self.document_ids:
            quality[str(document.id)] = document._quality_evidence_snapshot()
        return {'model':self._name,'id':self.id,'revision':self.evidence_revision,
                'values':data,'references':references,'quality_criteria':quality}

    def _approval_validate_submit(self):
        super()._approval_validate_submit()
        self._evidence_validate()

    def _approval_validate_step(self):
        super()._approval_validate_step()
        for record in self:
            record._evidence_validate()
            if record.approval_request_id.snapshot != record._approval_snapshot():
                raise UserError(_('상신 후 원천·첨부 내용이 달라졌습니다. 반려 후 다시 검토하십시오.'))

    def action_reset_approval(self):
        if any(record.evidence_state=='done' for record in self):
            raise UserError(_('완료 기록의 결재는 초기화하지 않습니다. 새 개정을 사용하십시오.'))
        return super().action_reset_approval()

    def action_complete_evidence(self):
        for record in self:
            record._approval_lock()
            if record.evidence_state=='done':continue
            record._approval_check_approved(_('증빙 완료'))
            record._approval_validate_step()
            values=record._evidence_completion_values()
            values.update({'evidence_state':'done',
                'completion_snapshot':record._approval_snapshot(),'completed_by_id':self.env.uid,
                'completed_at':fields.Datetime.now()})
            record.with_context(**{_CTX:_TOKEN}).write(values)
        return True

    def _evidence_completion_values(self):
        return {}

    def _evidence_revision_values(self):
        return {}

    def action_new_evidence_revision(self):
        self.ensure_one()
        self._approval_lock()
        if self.evidence_state!='done':
            raise UserError(_('완료된 기록에서만 새 개정을 만듭니다.'))
        latest=self.search([('evidence_key','=',self.evidence_key),('company_id','=',self.company_id.id)],order='evidence_revision desc',limit=1)
        if latest!=self:
            raise UserError(_('최신 개정에서 작업하십시오.'))
        values=self._evidence_revision_values()
        values.update({'evidence_key':self.evidence_key,
            'evidence_revision':self.evidence_revision+1,'previous_evidence_id':self.id,
            'evidence_state':'draft','completion_snapshot':False,'completed_by_id':False,'completed_at':False,
            'approval_line_ids':[Command.create({'sequence':line.sequence,'user_id':line.user_id.id}) for line in self.approval_request_id.line_ids]})
        new=self.with_context(**{_CTX:_TOKEN}).copy(values)
        return {'type':'ir.actions.act_window','res_model':self._name,'res_id':new.id,'view_mode':'form','target':'current'}


class Attachment(models.Model):
    _inherit = 'ir.attachment'

    @api.model
    def _cams_evidence_models(self):
        # Business modules extend this fixed list; no editable rule can add models.
        return ()

    def _check_cams_evidence_change(self):
        for model in self._cams_evidence_models():
            records = self.env[model].sudo().search([('attachment_ids','in',self.ids),
                '|',('evidence_state','=','done'),('approval_state','in',['in_progress','approved'])])
            if records:
                records._approval_lock()
                raise UserError(_('상신·완료 증빙의 첨부는 바꾸거나 삭제할 수 없습니다. 새 개정에 새 파일을 연결하십시오.'))

    def write(self, values):
        if {'datas','raw','db_datas','store_fname','name','mimetype','type','url','res_model','res_id','public','company_id'} & values.keys():
            self._check_cams_evidence_change()
        return super().write(values)

    def unlink(self):
        self._check_cams_evidence_change()
        return super().unlink()
