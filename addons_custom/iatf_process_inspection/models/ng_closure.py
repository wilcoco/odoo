"""Closing an NG inspection records its disposition; it never releases stock."""
from odoo import api,fields,models,_
from odoo.exceptions import AccessError,UserError

_TOKEN=object()
_PROTECTED={'ng_closure_snapshot','ng_closed_by_id','ng_closed_at'}


class ProcessNgClosure(models.Model):
    _inherit='iatf.process.inspection'
    ng_closure_note=fields.Text('NG 종료 확인·처리 근거')
    ng_closure_snapshot=fields.Json('NG 종료 당시 처리 근거',readonly=True,copy=False)
    ng_closed_by_id=fields.Many2one('res.users','NG 종료 확인자',readonly=True,copy=False)
    ng_closed_at=fields.Datetime('NG 종료 확인 시각',readonly=True,copy=False)

    def _approval_reset_ignored_fields(self):
        return super()._approval_reset_ignored_fields() | _PROTECTED

    def _has_ng(self):
        self.ensure_one()
        return self.result in ('fail','hold','conditional') or self.quantity_rejected>0 or any(line.result=='fail' for line in self.line_ids)

    def _ng_closure_evidence(self):
        self.ensure_one();self.check_access('write')
        if not self.env.su and not self.env.user.has_group('iatf_process_inspection.group_process_inspection_manager'):
            raise AccessError(_('NG 검사의 종료는 공정검사 책임자가 확인합니다.'))
        if self.state!='decided' or not self.auto_evidence_snapshot or not (self.ng_closure_note or '').strip():
            raise UserError(_('판정된 NG 검사와 종료 확인 근거가 필요합니다.'))
        nc=self.nonconformity_id
        nc.check_access('read');self._lock_auto_evidence_records(nc)
        if (not nc or nc.state!='closed' or nc.company_id!=self.company_id or nc.product_id!=self.product_id
            or nc.lot_id!=self.lot_id or nc.production_id!=self.production_id or not nc.verification_result
            or not nc.corrective_action_ids or any(ca.state not in ('verified','closed') or ca.effective!='yes'
                or not ca.verification_result or not ca.verification_date for ca in nc.corrective_action_ids)):
            raise UserError(_('동일 품번·LOT·생산지시의 부적합 조치·유효성 검증을 완료하고 종료하십시오.'))
        nc._approval_check_approved(_('NG 검사 종료 근거'))
        return {'inspection':self.auto_evidence_snapshot,'nonconformity_id':nc.id,
            'approval_request_id':nc.approval_request_id.id,'verification_result':nc.verification_result,
            'actions':nc.corrective_action_ids.read(['id','state']),
            'note':self.ng_closure_note,'lot_hold':self.lot_id.quality_hold if self.lot_id else False}

    @api.model_create_multi
    def create(self,vals_list):
        if any(key in values or 'default_'+key in self.env.context for values in vals_list for key in _PROTECTED):
            raise UserError(_('NG 종료 근거는 종료 확인 절차에서만 기록합니다.'))
        with self.env.cr.savepoint():
            records=super().create(vals_list)
            if any(row.state=='closed' and row._has_ng() for row in records):
                raise UserError(_('NG 검사는 판정·조치·종료 절차로 작성하십시오.'))
        return records

    def write(self,values):
        internal=self.env.context.get('_ng_close_token') is _TOKEN
        if not internal:
            if _PROTECTED & values.keys():raise UserError(_('NG 종료 확인자·시각·근거는 직접 수정할 수 없습니다.'))
            if 'ng_closure_note' in values and any(row.state=='closed' for row in self):
                raise UserError(_('종료 근거는 이력으로 보존합니다. 정정은 새 검사로 기록하십시오.'))
        with self.env.cr.savepoint():
            previously_closed=self.filtered(lambda row:row.state=='closed')
            closing=self.filtered(lambda row:row._has_ng() and row.state!='closed') if values.get('state')=='closed' else self.browse()
            if closing:
                self._lock_auto_evidence_records(closing)
                if any(key in values for key in self._AUTO_SOURCE_FIELDS | {'nonconformity_id','ng_closure_note'}):
                    raise UserError(_('검사·종료 근거를 먼저 저장한 뒤 종료 확인하십시오.'))
                snapshots={row.id:row._ng_closure_evidence() for row in closing}
            result=super().write(values)
            if values.get('state')=='closed' and any(row._has_ng() for row in self-previously_closed-closing):
                raise UserError(_('판정 결과와 종료 상태를 한 번에 지정할 수 없습니다. NG 종료 확인 절차를 사용하십시오.'))
            for row in closing:
                row.with_context(_ng_close_token=_TOKEN).write({'ng_closure_snapshot':snapshots[row.id],
                    'ng_closed_by_id':self.env.uid,'ng_closed_at':fields.Datetime.now()})
            return result
