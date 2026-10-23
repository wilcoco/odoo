"""Complete existing grinding/blending ledgers against actual LOT movements."""
from odoo import api,fields,models,Command,_
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare
from odoo.addons.iatf_document_control.models.inspection_evidence import _lock


class MaterialLedger(models.AbstractModel):
    _name='cams.material.ledger.mixin'
    _inherit=['cams.evidence.mixin']
    _description='기존 자재 장부 완료·개정 보호'

    @api.model_create_multi
    def create(self,vals_list):
        if not self._evidence_internal():
            for values in vals_list:
                if values.get('state',self.env.context.get('default_state','draft'))!='draft':
                    raise UserError(_('자재 장부는 초안으로 작성하고 검증 완료하십시오.'))
        return super().create(vals_list)

    def write(self,values):
        if not self._evidence_internal():
            if 'state' in values:raise UserError(_('장부 완료 상태는 검증 완료 절차에서만 변경합니다.'))
            if self._evidence_fields() & values.keys():
                self._approval_lock()
                if any(r.state=='done' for r in self):
                    raise UserError(_('기존 완료 장부도 수정하지 않습니다. 정정 개정으로 이력을 보존하십시오.'))
        return super().write(values)

    def unlink(self):
        if any(r.state=='done' for r in self):raise UserError(_('완료된 자재 장부는 삭제하지 않습니다.'))
        return super().unlink()

    def _approval_reset_ignored_fields(self):return super()._approval_reset_ignored_fields() | {'state'}
    def _evidence_completion_values(self):return dict(super()._evidence_completion_values(),state='done')
    def _evidence_revision_values(self):return dict(super()._evidence_revision_values(),state='draft')

    def _evidence_validate(self):
        super()._evidence_validate()
        if any(r.state!='draft' for r in self):
            raise UserError(_('기존 완료 기록은 그대로 보존합니다. 정정 개정에서 검토하십시오.'))

    def action_done(self):return self.action_complete_evidence()
    def action_draft(self):raise UserError(_('완료 이력은 초안으로 되돌리지 않습니다. 새 개정을 작성하십시오.'))

    def action_new_evidence_revision(self):
        self.ensure_one()
        if self.evidence_state=='done':return super().action_new_evidence_revision()
        # Legacy completed ledgers have no new approval snapshot. Copy a new
        # draft without inventing approval/completion for their historical row.
        self._approval_lock()
        if self.state!='done':raise UserError(_('완료 기록에서만 정정 개정을 만듭니다.'))
        if self.search_count([('previous_evidence_id','=',self.id)]):
            raise UserError(_('이미 만든 정정 개정을 사용하십시오.'))
        from odoo.addons.cams_evidence_core.models.evidence import _CTX,_TOKEN
        values=self._evidence_revision_values()
        values.update(evidence_key=self.evidence_key,evidence_revision=self.evidence_revision+1,
            previous_evidence_id=self.id,evidence_state='draft',completion_snapshot=False,completed_by_id=False,completed_at=False)
        new=self.with_context(**{_CTX:_TOKEN}).copy(values)
        return {'type':'ir.actions.act_window','res_model':self._name,'res_id':new.id,'view_mode':'form','target':'current'}


class RegrindLog(models.Model):
    _name='iatf.regrind.log'
    _inherit=['cams.material.ledger.mixin','iatf.regrind.log']
    product_id=fields.Many2one(related='source_product_id',store=True,readonly=False)
    record_date=fields.Date(related='regrind_date',store=True,readonly=False,default=None,precompute=True)
    responsible_id=fields.Many2one(related='operator_id',store=True,readonly=False,default=None,precompute=True)
    output_move_id=fields.Many2one('stock.move','산출 재생재 입고 이동',ondelete='restrict',check_company=True,
        help='완료된 생산→내부 재고 이동을 연결합니다. 이 기록의 완료 버튼은 재고를 새로 만들지 않습니다.')
    @api.depends('blend_line_ids.qty','blend_line_ids.blend_id.state','blend_line_ids.blend_id.evidence_revision')
    def _compute_used(self):
        for record in self:
            latest={}
            for blend in record.blend_line_ids.blend_id:
                key=blend.evidence_key or str(blend.id)
                score=(blend.state=='done',blend.evidence_revision,blend.id)
                if key not in latest or score>latest[key][0]:latest[key]=(score,blend)
            record.used_qty=sum(line.qty for _,blend in latest.values() for line in blend.line_ids if line.regrind_log_id==record)
    def _evidence_fields(self):
        return super()._evidence_fields() | {'source_product_id','regrind_date','operator_id','shift','equipment_id',
            'source_type','input_qty','output_qty','output_lot_id','output_lot_name','foreign_check','foreign_action','storage_location','output_move_id'}
    def unlink(self):
        self.check_access('unlink')
        if self.env['iatf.blend.log.line'].sudo().search_count([('regrind_log_id','in',self.ids)]):
            raise UserError(_('배합에 연결된 분쇄 출처는 삭제할 수 없습니다.'))
        return super().unlink()

    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            missing=record._missing_for_done()
            move=record.output_move_id
            if missing or not record.output_lot_id or not move or not record.equipment_id or not record.lot_id:
                raise UserError(_('이물 점검·투입 LOT·산출 LOT·설비·실제 산출 입고 이동을 연결하십시오.'))
            move.check_access('read');move.move_line_ids.check_access('read')
            _lock(move);_lock(move.move_line_ids)
            kg=self.env.ref('uom.product_uom_kgm')
            if (move.state!='done' or move.company_id!=record.company_id
                or move.product_id!=record.output_lot_id.product_id
                or move.location_id.usage!='production' or move.location_dest_id.usage!='internal'
                or move.product_uom.category_id!=kg.category_id
                or any(line.lot_id!=record.output_lot_id for line in move.move_line_ids)):
                raise UserError(_('산출 LOT와 같은 품목·회사·kg 단위의 완료 생산 입고 이동이어야 합니다.'))
            quantity=move.product_uom._compute_quantity(move.quantity,kg)
            if float_compare(quantity,record.output_qty,precision_rounding=kg.rounding)!=0:
                raise UserError(_('실제 산출 입고 수량과 분쇄 산출량이 다릅니다.'))
            if self.search_count([('output_move_id','=',move.id),('state','=','done'),('evidence_key','!=',record.evidence_key)]):
                raise UserError(_('같은 산출 입고 이동을 다른 분쇄 장부에서 중복 사용할 수 없습니다.'))

    def _approval_snapshot(self):
        result=super()._approval_snapshot()
        move=self.output_move_id
        result['output_move']={'id':move.id,'state':move.state,'quantity':move.quantity,
            'product':move.product_id.id,'lot_ids':move.move_line_ids.lot_id.ids,
            'source':move.location_id.id,'destination':move.location_dest_id.id} if move else False
        return result


class BlendLog(models.Model):
    _name='iatf.blend.log'
    _inherit=['cams.material.ledger.mixin','iatf.blend.log']
    record_date=fields.Date(related='blend_date',store=True,readonly=False,default=None,precompute=True)
    responsible_id=fields.Many2one(related='operator_id',store=True,readonly=False,default=None,precompute=True)
    def _evidence_fields(self):
        return super()._evidence_fields() | {'blend_date','operator_id','shift','equipment_id','production_id','line_ids','ng_action'}
    def _evidence_calculated_fields(self):
        return super()._evidence_calculated_fields() | {'standard_id','limit_ratio','limit_additive_ratio','ratio_basis','result',
            'virgin_qty','regrind_qty','additive_qty','resin_qty','total_qty','regrind_ratio','additive_ratio'}
    def _evidence_revision_values(self):
        return dict(super()._evidence_revision_values(),line_ids=[Command.create({
            'sequence':l.sequence,'material_type':l.material_type,'product_id':l.product_id.id,
            'lot_id':l.lot_id.id,'regrind_log_id':l.regrind_log_id.id,'qty':l.qty,'note':l.note}) for l in self.line_ids])
    def _evidence_validate(self):
        super()._evidence_validate()
        for record in self:
            if record._missing_for_done() or not record.lot_id or not record.equipment_id or not record.standard_id:
                raise UserError(_('LOT·설비·배합 기준·투입 내역·이상 조치를 확인하십시오.'))
            if record.standard_id.company_id and record.standard_id.company_id!=record.company_id:
                raise UserError(_('다른 회사의 배합 기준입니다.'))
            for line in record.line_ids:
                if (not line.lot_id or line.lot_id.product_id!=line.product_id
                    or line.lot_id.company_id!=record.company_id):
                    raise UserError(_('모든 투입 자재에 같은 회사·품번의 원료 LOT를 연결하십시오.'))
                if line.material_type=='regrind':
                    source=line.regrind_log_id
                    source.check_access('read');_lock(source)
                    latest_source=self.env['iatf.regrind.log'].search([('evidence_key','=',source.evidence_key),
                        ('company_id','=',record.company_id.id),('evidence_state','=','done')],order='evidence_revision desc',limit=1)
                    if (source.evidence_state!='done' or source.output_lot_id!=line.lot_id or source.company_id!=record.company_id
                        or source.foreign_check!='ok' or source!=latest_source):
                        raise UserError(_('검증 완료된 분쇄 산출 LOT와 재생재 투입 LOT가 일치해야 합니다.'))
                    sample=self.env['cams.grind.sample'].search([('regrind_log_id','=',source.id),('evidence_state','=','done')],
                        order='record_date desc,evidence_revision desc,id desc',limit=1)
                    if sample and sample.result!='usable':
                        raise UserError(_('분쇄 입자 점검에서 상세 검사·사용 불가인 LOT는 배합에 투입할 수 없습니다.'))
                    # Revisions describe one consumption, not an extra batch.
                    other_lines=self.env['iatf.blend.log.line'].search([('regrind_log_id','=',source.id),
                        ('blend_id.state','=','done'),('blend_id.evidence_key','!=',record.evidence_key)])
                    latest={}
                    for other in other_lines.blend_id:
                        previous=latest.get(other.evidence_key)
                        if not previous or previous.evidence_revision<other.evidence_revision:latest[other.evidence_key]=other
                    used=sum(l.qty for doc in latest.values() for l in doc.line_ids if l.regrind_log_id==source)
                    current=sum(record.line_ids.filtered(lambda l:l.regrind_log_id==source).mapped('qty'))
                    if float_compare(used+current,source.output_qty,precision_digits=3)>0:
                        raise UserError(_('분쇄 산출량보다 재생재 투입 누계가 많습니다.'))
    def _approval_snapshot(self):
        result=super()._approval_snapshot()
        result['inputs']=[{key:line[key].id if line._fields[key].relational else line[key]
            for key in ('sequence','material_type','product_id','lot_id','regrind_log_id','qty','note')} for line in self.line_ids.sorted('id')]
        result['ratio']={key:self[key] if not self._fields[key].relational else self[key].id
            for key in ('standard_id','limit_ratio','limit_additive_ratio','ratio_basis','result','regrind_ratio','additive_ratio')}
        return result


class BlendLine(models.Model):
    _inherit='iatf.blend.log.line'
    def _check_editable_parents(self,parents):
        parents._approval_lock()
        if any(p.state=='done' or p.evidence_state=='done' or p.approval_state in ('in_progress','approved') for p in parents):
            raise UserError(_('상신·완료된 배합의 투입 내역은 변경하지 않습니다.'))
    @api.model_create_multi
    def create(self,vals_list):
        ids=[v.get('blend_id',self.env.context.get('default_blend_id')) for v in vals_list]
        self._check_editable_parents(self.env['iatf.blend.log'].browse([i for i in ids if i]))
        return super().create(vals_list)
    def write(self,values):
        parents=self.blend_id
        if values.get('blend_id'):parents|=self.env['iatf.blend.log'].browse(values['blend_id'])
        self._check_editable_parents(parents)
        return super().write(values)
    def unlink(self):
        self._check_editable_parents(self.blend_id)
        return super().unlink()


class Attachment(models.Model):
    _inherit='ir.attachment'
    @api.model
    def _cams_evidence_models(self):
        return super()._cams_evidence_models()+('iatf.regrind.log','iatf.blend.log')
