"""Receipt-scoped inspection, immutable approval snapshot and stock disposition."""
import math
from markupsafe import escape
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare
from odoo.addons.iatf_document_control.models.inspection_evidence import (
    inspection_documents_snapshot, validate_inspection_links)
from .iqc_service import service, is_service

_SOURCE = {'receipt_move_line_id','receipt_snapshot','picking_id','purchase_id','supplier_id',
           'company_id','product_id','product_uom_id','lot_id','quantity_received'}
_SYSTEM = {'state','approved_by','nonconformity_id','inspector_id','nonconformity_history_ids','nonconformity_snapshot'}
_EVIDENCE = {'quantity_inspected','quantity_accepted','quantity_rejected','inspection_type',
            'sampling_plan','sample_size','accept_number','reject_number','line_ids','visual_result',
            'dimension_result','material_result','supplier_cert_no','result','disposition',
            'document_ids','attachment_ids','inspection_date','notes'}


class IncomingInspection(models.Model):
    _inherit = 'iatf.incoming.inspection'

    receipt_move_line_id = fields.Many2one('stock.move.line', readonly=True, copy=False, index=True, ondelete='restrict')
    receipt_snapshot = fields.Json(readonly=True, copy=False)
    product_uom_id = fields.Many2one('uom.uom', string='입고 단위', readonly=True, copy=False)
    nonconformity_history_ids = fields.Many2many('iatf.nonconformity',string='이전 부적합 판정 기록',readonly=True,copy=False)
    nonconformity_summary = fields.Char(string='부적합 판정 이력',compute='_compute_nc_summary')
    nonconformity_snapshot = fields.Json(readonly=True,copy=False)
    movement_ids = fields.One2many('stock.move', 'iqc_inspection_id', readonly=True)
    quantity_released = fields.Float(string='이동 완료 합격 수량', compute='_compute_disposed')
    quantity_returned = fields.Float(string='실제 반품 수량', compute='_compute_disposed')
    quantity_unresolved = fields.Float(string='미판정 수량', compute='_compute_disposed')
    quantity_pending = fields.Float(string='물리적 검사대기 수량', compute='_compute_disposed')

    _sql_constraints = [('iqc_receipt_detail_unique','unique(receipt_move_line_id)',
                         '입고 상세별 수입검사는 한 번만 생성됩니다.')]

    @api.depends('nonconformity_history_ids')
    def _compute_nc_summary(self):
        for record in self:
            record.nonconformity_summary=', '.join(record.sudo().nonconformity_history_ids.mapped('name'))

    @api.model
    def _iqc_receipt_values(self, line):
        return {name: value for name, value in {
            'line': line.id, 'move': line.move_id.id, 'picking': line.picking_id.id,
            'company': line.company_id.id, 'product': line.product_id.id,
            'supplier': line.picking_id.partner_id.id,
            'uom': line.product_uom_id.id, 'quantity': line.quantity,
            'lot': line.lot_id.id or False, 'owner': line.owner_id.id or False,
            'package': line.result_package_id.id or False, 'pending': line.location_dest_id.id,
            'release': line.iqc_release_location_id.id, 'supplier_location': line.location_id.id,
            'purchase_line': line.move_id.purchase_line_id.id or False,
        }.items()}

    @api.model_create_multi
    def create(self, vals_list):
        if not is_service(self.env):
            for vals in vals_list:
                for field in {'receipt_move_line_id','receipt_snapshot'} | _SYSTEM:
                    value=vals.get(field,self.env.context.get('default_'+field))
                    if value and not (field=='state' and value=='draft'):
                        raise UserError(_('입고 범위와 검사 처리 근거는 해당 업무 액션으로만 기록합니다.'))
                company=self.env['res.company'].browse(vals.get('company_id',self.env.context.get('default_company_id',self.env.company.id)))
                if not self.env.su and company not in self.env.companies:
                    raise AccessError(_('허용된 회사에만 수입검사를 만들 수 있습니다.'))
        with self.env.cr.savepoint():
            records = super().create(vals_list)
            validate_inspection_links(records)
            return records

    def write(self, vals):
        if not is_service(self.env):
            if _SYSTEM & vals.keys():
                raise UserError(_('검사 상태·처리자는 공개 업무 액션으로 기록합니다.'))
            if {'receipt_move_line_id','receipt_snapshot'} & vals.keys() or (
                    _SOURCE & vals.keys() and self.filtered('receipt_move_line_id')):
                raise UserError(_('입고 원천과 실제 입고 수량은 수정할 수 없습니다.'))
            if _EVIDENCE & vals.keys():
                self._iqc_assert_editable()
        with self.env.cr.savepoint():
            result = super().write(vals)
            if {'document_ids', 'attachment_ids', 'company_id'} & vals.keys():
                validate_inspection_links(self)
            return result

    def unlink(self):
        if self.filtered('receipt_move_line_id'):
            raise UserError(_('입고 수입검사와 처리 이력은 삭제하지 않습니다.'))
        return super().unlink()

    def _approval_reset_ignored_fields(self):
        return super()._approval_reset_ignored_fields() | _SYSTEM | {'movement_ids'}

    def _iqc_actor(self, quality=True):
        self.check_access('write' if quality else 'read')
        group='iatf_incoming_inspection.group_incoming_inspection_user' if quality else 'stock.group_stock_user'
        if not self.env.su and not self.env.user.has_group(group):
            raise AccessError(_('해당 품질 또는 물류 담당 권한이 필요합니다.'))
        for rec in self:
            if not self.env.su and rec.company_id not in self.env.companies:
                raise AccessError(_('허용된 회사의 수입검사만 처리할 수 있습니다.'))

    def _iqc_lock(self):
        self.flush_recordset()
        if self.ids:
            self.env.cr.execute('UPDATE iatf_incoming_inspection SET write_date=write_date WHERE id IN %s', [tuple(sorted(self.ids))])
            self.invalidate_recordset()

    def _iqc_assert_editable(self):
        self._iqc_actor()
        self._iqc_lock()
        for rec in self:
            if rec.state in ('closed','cancelled') or rec.approval_state in ('in_progress','approved'):
                raise UserError(_('확정 검사 근거를 수정하려면 먼저 재검토를 시작하세요. 과거 결재는 보존됩니다.'))

    def _iqc_source(self):
        self.ensure_one()
        line=self.receipt_move_line_id.sudo()
        if (not line or line.state!='done' or not line.iqc_receipt_managed
                or not line.location_dest_id.iqc_pending or not self.receipt_snapshot
                or self.receipt_snapshot != self._iqc_receipt_values(line)):
            raise UserError(_('실제 입고 상세와 검사대기 범위가 확인되지 않습니다. 기존 자료는 이관 확인이 필요합니다.'))
        if (self.company_id != line.company_id or self.product_id != line.product_id
                or self.product_uom_id != line.product_uom_id or self.lot_id != line.lot_id
                or self.quantity_received != line.quantity or self.picking_id != line.picking_id
                or self.supplier_id != line.picking_id.partner_id):
            raise UserError(_('검사와 원 입고의 회사·제품·단위·LOT·수량이 일치하지 않습니다.'))
        return line

    def _iqc_totals(self, kind, states=('done',)):
        self.ensure_one()
        moves=self.sudo().movement_ids.filtered(lambda m:m.iqc_movement_kind==kind and m.state in states)
        for move in moves:
            qty=move.quantity if move.state=='done' else move.product_uom_qty
            if (not math.isfinite(qty) or qty<0 or move.company_id!=self.company_id
                    or move.product_id!=self.product_id or move.product_uom.category_id!=self.product_uom_id.category_id):
                raise UserError(_('처리 전표의 수량·회사·제품·단위가 검사 범위와 다릅니다.'))
        return sum(m.product_uom._compute_quantity(m.quantity if m.state=='done' else m.product_uom_qty,self.product_uom_id) for m in moves)

    @api.depends('quantity_received','quantity_accepted','quantity_rejected','movement_ids.state','movement_ids.quantity')
    def _compute_disposed(self):
        for rec in self:
            rec.quantity_released=rec._iqc_totals('release') if rec.product_uom_id else 0
            rec.quantity_returned=rec._iqc_totals('return') if rec.product_uom_id else 0
            rec.quantity_unresolved=rec.quantity_received-rec.quantity_accepted-rec.quantity_rejected
            rec.quantity_pending=rec.quantity_received-rec.quantity_released-rec.quantity_returned

    def _iqc_validate_evidence(self):
        self.ensure_one()
        self._iqc_source()
        rounding=self.product_uom_id.rounding
        values=[self.quantity_received,self.quantity_inspected,self.quantity_accepted,self.quantity_rejected]
        if any(not math.isfinite(v) or v<0 for v in values):
            raise UserError(_('검사 수량은 유한한 0 이상의 값이어야 합니다.'))
        received, inspected, accepted, rejected=values
        if inspected<=0 or float_compare(inspected,received,precision_rounding=rounding)>0:
            raise UserError(_('실제 검사한 샘플 수량을 입고 수량 이내로 입력하세요.'))
        if float_compare(accepted+rejected,received,precision_rounding=rounding)>0:
            raise UserError(_('합격·불합격 처분 수량의 합은 실제 입고 수량을 넘을 수 없습니다.'))
        if not accepted+rejected or not self.inspector_id or not self.line_ids:
            raise UserError(_('검사원·검사 항목·실제 처분 수량이 필요합니다.'))
        if self.inspection_type not in ('full','sampling') or self.result=='conditional' or self.disposition in ('concession','rework'):
            raise UserError(_('검사 면제·성적서 대체·특채·재작업 조건은 별도 정책 확인 전 재고를 해제할 수 없습니다.'))
        if self.inspection_type=='full' and float_compare(inspected,accepted+rejected,precision_rounding=rounding)<0:
            raise UserError(_('전수검사는 처분할 수량 이상을 실제 검사해야 합니다.'))
        if self.inspection_type=='sampling' and (not self.sampling_plan or self.sample_size<=0 or
                self.sample_size != inspected or self.accept_number<0 or self.reject_number<=self.accept_number):
            raise UserError(_('샘플 검사에는 검토된 샘플링 기준·샘플 수량·Ac/Re가 필요합니다.'))
        for line in self.line_ids:
            if not line.characteristic_name or not line.specification or not line.measured_value or line.result not in ('pass','fail','na'):
                raise UserError(_('모든 검사 항목에 규격·실측/관찰 근거·판정을 입력하세요.'))
            if line.result=='na' and not line.notes:
                raise UserError(_('검사 항목 해당 없음은 사유가 필요합니다.'))
        if self.result=='pass' and (rejected or any(l.result=='fail' for l in self.line_ids)):
            raise UserError(_('불합격 근거가 있는 범위를 전체 합격으로 판정할 수 없습니다.'))
        if self.result=='fail' and (accepted or not rejected):
            raise UserError(_('불합격 판정은 불합격 처분 수량만 지정하세요.'))
        if self.result not in ('pass','partial','fail'):
            raise UserError(_('합격·부분 합격·불합격 판정이 필요합니다.'))
        if self.result=='pass' and float_compare(accepted,received,precision_rounding=rounding)!=0:
            raise UserError(_('잔량이 있는 합격은 부분 합격으로 기록하세요.'))
        if self.result=='partial' and not accepted:
            raise UserError(_('부분 합격에는 합격 처분 수량이 필요합니다.'))
        if self.disposition not in ('accept','return','sort'):
            raise UserError(_('실제 처분 방법을 지정하세요.'))
        for kind,limit in [('release',accepted),('return',rejected)]:
            if float_compare(self._iqc_totals(kind),limit,precision_rounding=rounding)>0:
                raise UserError(_('이미 이동·반품한 실제 수량보다 처분 수량을 줄일 수 없습니다.'))
        return True

    def _iqc_evidence_snapshot(self):
        self.ensure_one()
        result={'receipt':self.receipt_snapshot,'inspector_id':self.inspector_id.id}
        for key in sorted(_EVIDENCE-{'line_ids','document_ids','attachment_ids'}):
            value=self[key]
            result[key]=str(value) if key=='inspection_date' else value
        result['document_ids']=self.document_ids.ids
        result['attachment_ids']=self.attachment_ids.ids
        linked = inspection_documents_snapshot(self)
        if linked:
            result['linked_evidence'] = linked
        result['lines']=[{key:line[key] for key in ('sequence','characteristic_name','characteristic_type',
            'specification','measurement_method','measured_value','result','notes')} for line in self.line_ids]
        return result

    def action_start_inspection(self):
        self._iqc_assert_editable()
        for rec in self:
            if rec.state!='draft':
                raise UserError(_('초안 검사만 시작할 수 있습니다.'))
            rec._iqc_source()
            service(rec).write({'state':'inspecting','inspector_id':self.env.uid})
        return True

    def action_decide(self):
        self._iqc_actor()
        self._iqc_lock()
        for rec in self:
            if rec.state!='inspecting':
                raise UserError(_('진행 중인 검사만 판정할 수 있습니다.'))
            rec._iqc_validate_evidence()
            service(rec).write({'state':'decided'})
            if rec.quantity_rejected:
                rec._auto_create_nc()
        return True

    def _auto_create_nc(self):
        self.ensure_one()
        self._iqc_actor()
        snapshot=self._iqc_evidence_snapshot()
        if self.nonconformity_id and self.nonconformity_snapshot==snapshot:
            return self.nonconformity_id
        nc=self.env['iatf.nonconformity'].sudo().with_company(self.company_id).create({
            'title':_('수입검사 불합격: %s') % self.name, 'nc_type':'supplier','severity':'major',
            'problem_description':'<p>%s</p>' % escape(_('입고 상세 %s / 검사 %s / 불합격 %s %s') %
                (self.receipt_move_line_id.id,self.name,self.quantity_rejected,self.product_uom_id.name)),
            'company_id':self.company_id.id,'product_id':self.product_id.id,'lot_id':self.lot_id.id,
            'partner_id':self.supplier_id.id,
            'quantity_affected':self.product_uom_id._compute_quantity(self.quantity_received,self.product_id.uom_id),
            'quantity_rejected':self.product_uom_id._compute_quantity(self.quantity_rejected,self.product_id.uom_id)})
        if self.nonconformity_id:
            nc.message_post(body=_('입고검사 재검토에 따른 새 판정입니다. 이전 기록 %s는 그대로 보존하며 자동 종결하지 않습니다.') % self.nonconformity_id.sudo().name)
        service(self).write({'nonconformity_id':nc.id,'nonconformity_snapshot':snapshot,
            'nonconformity_history_ids':[(4,nc.id)]})
        return nc

    def action_create_nc(self):
        self.ensure_one()
        self._iqc_actor()
        self._iqc_validate_evidence()
        if not self.quantity_rejected:
            raise UserError(_('불합격 수량이 필요합니다.'))
        nc=self._auto_create_nc()
        if nc.with_user(self.env.user).has_access('read'):
            return {'type':'ir.actions.act_window','res_model':'iatf.nonconformity','res_id':nc.id,'view_mode':'form'}
        return {'type':'ir.actions.act_window','res_model':self._name,'res_id':self.id,'view_mode':'form'}

    def action_reset_inspection(self):
        self._iqc_actor()
        self._iqc_lock()
        for rec in self:
            if rec.sudo().movement_ids.filtered(lambda m:m.state not in ('done','cancel')):
                raise UserError(_('물류 담당자가 미완료 해제·반품 전표를 먼저 취소해야 재검토할 수 있습니다.'))
            rec.action_reset_approval()
            service(rec).write({'state':'inspecting','inspector_id':self.env.uid,'approved_by':False})
        return True

    def action_cancel(self):
        self._iqc_actor()
        if self.filtered('receipt_move_line_id'):
            raise UserError(_('실제 입고 검사는 취소로 없애지 않습니다. 재검토 또는 실제 반품으로 처리하세요.'))
        service(self).write({'state':'cancelled'})

    def action_close(self):
        self._iqc_actor()
        self._iqc_lock()
        for rec in self:
            rec._approval_check_approved(_('수입검사 마감'))
            rec._iqc_validate_evidence()
            if (rec.sudo().movement_ids.filtered(lambda m:m.state not in ('done','cancel')) or
                    float_compare(rec.quantity_pending,0,precision_rounding=rec.product_uom_id.rounding)!=0):
                raise UserError(_('검사대기 전량의 실제 해제·반품 완료 후 종료할 수 있습니다.'))
            service(rec).write({'state':'closed'})
        return True

    def _iqc_validate_approval(self):
        self.ensure_one()
        self._approval_check_approved(_('검사대기 재고 처리'))
        self._iqc_validate_evidence()
        if self.approval_request_id.iqc_scope_snapshot != self._iqc_evidence_snapshot():
            raise UserError(_('현재 검사 근거가 승인 시점과 달라 재검토가 필요합니다.'))

    def _iqc_validate_movement(self, move):
        self.ensure_one()
        self._iqc_actor(quality=False)
        self._iqc_lock()
        self._iqc_validate_approval()
        line=self._iqc_source()
        kind=move.iqc_movement_kind
        destination=line.iqc_release_location_id if kind=='release' else line.location_id
        if (kind not in ('release','return') or move.iqc_approval_request_id != self.approval_request_id
                or move.company_id!=self.company_id or move.product_id!=self.product_id
                or move.location_id!=line.location_dest_id or move.location_dest_id!=destination
                or move.product_uom!=self.product_uom_id):
            raise UserError(_('IQC 승인 범위와 실제 이동의 제품·회사·단위·위치가 다릅니다.'))
        if kind=='release' and (move.purchase_line_id or move.origin_returned_move_id):
            raise UserError(_('내부 해제는 구매 입고·반품 수량을 변경하지 않습니다.'))
        if kind=='return' and (move.origin_returned_move_id!=line.move_id or move.purchase_line_id!=line.move_id.purchase_line_id):
            raise UserError(_('반품은 원 입고와 구매 라인을 보존해야 합니다.'))
        if line.lot_id:
            line.lot_id.flush_recordset()
            self.env.cr.execute('UPDATE stock_lot SET write_date=write_date WHERE id=%s',[line.lot_id.id])
            line.lot_id.invalidate_recordset()
        if kind=='release' and line.lot_id.quality_hold:
            raise UserError(_('별도로 설정된 LOT 품질 보류는 IQC 합격만으로 해제하지 않습니다.'))
        limit=self.quantity_accepted if kind=='release' else self.quantity_rejected
        states=('draft','waiting','confirmed','assigned','partially_available','done')
        if float_compare(self._iqc_totals(kind,states),limit,precision_rounding=self.product_uom_id.rounding)>0:
            raise UserError(_('기존 처리와 진행 중인 전표를 포함해 승인된 처분 수량을 초과했습니다.'))
        if not math.isfinite(move.product_uom_qty) or move.product_uom_qty<=0:
            raise UserError(_('처리 수량은 양수여야 합니다.'))
        qty=0
        for ml in move.move_line_ids.filtered(lambda ml:ml.quantity):
            if (ml.product_id!=line.product_id or ml.product_uom_id!=line.product_uom_id or ml.lot_id!=line.lot_id
                    or ml.owner_id!=line.owner_id or ml.package_id!=line.result_package_id
                    or ml.location_id!=line.location_dest_id or ml.location_dest_id!=destination
                    or ml.company_id!=line.company_id or ml.quantity<0 or not math.isfinite(ml.quantity)):
                raise UserError(_('처리 상세의 LOT·소유자·포장·단위·수량이 원 입고 범위를 벗어났습니다.'))
            qty+=ml.quantity
        if float_compare(qty,move.product_uom_qty,precision_rounding=self.product_uom_id.rounding)>0:
            raise UserError(_('실제 처리 수량은 승인 요청 수량을 넘을 수 없습니다.'))

    def _iqc_prepare_movement(self, kind):
        self.ensure_one()
        self._iqc_actor(quality=False)
        with self.env.cr.savepoint():
            self._iqc_lock()
            self._iqc_validate_approval()
            line=self._iqc_source()
            active=('draft','waiting','confirmed','assigned','partially_available','done')
            limit=self.quantity_accepted if kind=='release' else self.quantity_rejected
            quantity=limit-self._iqc_totals(kind,active)
            if float_compare(quantity,0,precision_rounding=self.product_uom_id.rounding)<=0:
                raise UserError(_('추가 처리할 승인 수량이 없습니다.'))
            warehouse=line.location_dest_id.iqc_warehouse_id
            dest=line.iqc_release_location_id if kind=='release' else line.location_id
            ptype=warehouse.int_type_id if kind=='release' else (self.picking_id.picking_type_id.return_picking_type_id or warehouse.out_type_id)
            Picking=service(self.env['stock.picking'].sudo().with_company(self.company_id))
            picking=Picking.create({'picking_type_id':ptype.id,'company_id':self.company_id.id,
                'partner_id':self.supplier_id.id,'location_id':line.location_dest_id.id,
                'location_dest_id':dest.id,'origin':self.name})
            vals={'name':self.name,'picking_id':picking.id,'company_id':self.company_id.id,
                'product_id':self.product_id.id,'product_uom':self.product_uom_id.id,'product_uom_qty':quantity,
                'location_id':line.location_dest_id.id,'location_dest_id':dest.id,
                'iqc_inspection_id':self.id,'iqc_approval_request_id':self.approval_request_id.id,
                'iqc_movement_kind':kind,'procure_method':'make_to_stock'}
            if kind=='return':
                vals.update(origin_returned_move_id=line.move_id.id,purchase_line_id=line.move_id.purchase_line_id.id,
                            to_refund=True)
            move=service(self.env['stock.move'].sudo().with_company(self.company_id)).create(vals)
            move._action_confirm(merge=False)
            move._action_assign()
            if float_compare(move.quantity,quantity,precision_rounding=self.product_uom_id.rounding)!=0:
                raise UserError(_('해당 입고 범위에 예약 가능한 실제 검사대기 재고가 부족합니다.'))
            move._iqc_check_pending_move()
            return {'type':'ir.actions.act_window','res_model':'stock.picking','res_id':picking.id,'view_mode':'form'}

    def action_prepare_release(self):
        return self._iqc_prepare_movement('release')

    def action_prepare_return(self):
        return self._iqc_prepare_movement('return')


class IncomingInspectionLine(models.Model):
    _inherit='iatf.incoming.inspection.line'

    @api.model_create_multi
    def create(self, vals_list):
        if not is_service(self.env):
            parents=self.env['iatf.incoming.inspection'].browse([v.get('inspection_id',self.env.context.get('default_inspection_id')) for v in vals_list])
            parents._iqc_assert_editable()
        return super().create(vals_list)

    def write(self, vals):
        if not is_service(self.env):
            if 'inspection_id' in vals:
                raise UserError(_('검사 항목을 다른 검사에 재귀속할 수 없습니다.'))
            self.inspection_id._iqc_assert_editable()
        return super().write(vals)

    def unlink(self):
        if not is_service(self.env):
            self.inspection_id._iqc_assert_editable()
        return super().unlink()


class ApprovalRequest(models.Model):
    _inherit='iatf.approval.request'

    iqc_scope_snapshot=fields.Json(string='승인 당시 입고 검사 근거',readonly=True,copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('iqc_scope_snapshot',self.env.context.get('default_iqc_scope_snapshot')) for v in vals_list):
            raise UserError(_('승인 검사 근거는 상신 시 서버가 기록합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'iqc_scope_snapshot' in vals and not is_service(self.env):
            raise UserError(_('승인 검사 근거는 직접 바꿀 수 없습니다.'))
        return super().write(vals)

    def action_submit(self):
        with self.env.cr.savepoint():
            for request in self:
                if request.res_model=='iatf.incoming.inspection' and request.state=='draft' and request.guard_version:
                    record=request._lock_workflow()
                    record._iqc_actor()
                    if record.state!='decided':
                        raise UserError(_('실제 검사 판정 후 상신하세요.'))
                    record._iqc_validate_evidence()
                    service(request).write({'iqc_scope_snapshot':record._iqc_evidence_snapshot()})
            return super().action_submit()

    def _approve_user(self,user):
        if self.res_model=='iatf.incoming.inspection':
            record=self._lock_workflow()
            record._iqc_actor()
            record._iqc_validate_evidence()
            if self.iqc_scope_snapshot!=record._iqc_evidence_snapshot():
                raise UserError(_('상신 후 검사 근거가 변경되었습니다. 재검토하세요.'))
        result=super()._approve_user(user)
        if self.res_model=='iatf.incoming.inspection' and self.state=='approved':
            service(self._get_target_record()).write({'approved_by':user.id})
        return result
