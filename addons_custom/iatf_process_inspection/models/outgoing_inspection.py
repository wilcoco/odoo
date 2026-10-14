"""Bind common approval to the exact outgoing inspection; no second approval engine."""
import math

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.iatf_document_control.models.inspection_evidence import (
    inspection_documents_snapshot, validate_inspection_links)

_SNAPSHOT_TOKEN = object()


class OutgoingInspectionMixin(models.AbstractModel):
    _name = 'iatf.outgoing.inspection.mixin'
    _description = 'Exact outgoing inspection approval scope'

    quantity_uom_id = fields.Many2one('uom.uom', string='검사 수량 단위')
    outgoing_approval_snapshot = fields.Json(string='상신한 출고 검사 기준', readonly=True, copy=False)
    outgoing_decision_snapshot = fields.Json(string='출하 판정 당시 근거', readonly=True, copy=False)
    outgoing_decided_by_id = fields.Many2one('res.users', string='실제 출하 판정자',
        compute='_compute_outgoing_decision')
    outgoing_decided_at = fields.Datetime(string='출하 판정 기록 시각', compute='_compute_outgoing_decision')
    outgoing_can_cancel = fields.Boolean(string='미출고 검사 정정 가능', compute='_compute_outgoing_can_cancel')

    @api.depends('state', 'picking_id.state', 'picking_id.picking_type_code')
    def _compute_outgoing_can_cancel(self):
        for record in self:
            # Display hint only: the server still checks the actual picking
            # state and preserves frozen decision/approval records on write.
            record.outgoing_can_cancel = bool(record.picking_id and
                record.picking_id.picking_type_code == 'outgoing' and
                record.picking_id.state not in ('done', 'cancel') and record.state != 'cancelled')

    @api.depends('outgoing_decision_snapshot')
    def _compute_outgoing_decision(self):
        for record in self:
            basis = record.outgoing_decision_snapshot or {}
            record.outgoing_decided_by_id = basis.get('by', False)
            record.outgoing_decided_at = basis.get('at', False)

    def _approval_reset_ignored_fields(self):
        return super()._approval_reset_ignored_fields() | {'outgoing_decision_snapshot'}

    def _outgoing_decision_payload(self):
        self.ensure_one()
        data = self._outgoing_payload()
        # Supporting documents may be added for review after the physical result
        # was recorded. Their content is frozen separately by common approval.
        data.pop('linked_evidence', None)
        data.update(inspector_id=self.inspector_id.id, notes=self.notes)
        if self._name == 'iatf.process.inspection':
            data['source'] = self._auto_source_payload()['source']
        else:
            data.update(shipping_date=str(self.shipping_date), destination=self.destination)
        return data

    def _assert_outgoing_decided(self):
        for record in self:
            basis = record.outgoing_decision_snapshot
            if (not isinstance(basis, dict) or basis.get('version') != 1 or
                    basis.get('model') != record._name or basis.get('id') != record.id or
                    not basis.get('by') or basis.get('by') != record.inspector_id.id or
                    not basis.get('at') or basis.get('payload') != record._outgoing_decision_payload()):
                raise UserError(_('현재 출하검사와 일치하는 실제 판정 근거가 없습니다. 검사자가 판정 절차를 수행해야 합니다. 이미 판정한 내용의 정정은 새 검사로 남기세요.'))
            if record._name == 'iatf.process.inspection' and (
                    not record.auto_evidence_snapshot or not record._auto_source_matches(
                        record.auto_evidence_snapshot.get('source'))):
                raise UserError(_('OQC의 실제 판정·자동 연동 원검사 근거가 일치하지 않습니다.'))
        return True

    def action_decide(self):
        outgoing = self.filtered(lambda record: record._is_outgoing_inspection())
        with self.env.cr.savepoint():
            outgoing.check_access('write')
            outgoing._check_outgoing_identity()
            outgoing.picking_id.sudo()._lock_outgoing()
            outgoing._approval_lock_target()
            outgoing.invalidate_recordset()
            previous = outgoing.filtered('outgoing_decision_snapshot')
            previous._assert_outgoing_decided()
            for record in outgoing:
                if record.inspector_id != self.env.user:
                    raise UserError(_('실제 로그인한 검사자가 본인 명의로 출하 판정하십시오.'))
                if record.picking_id.state in ('done', 'cancel') or record.state == 'cancelled':
                    raise UserError(_('종료·취소 출고 또는 취소 검사에는 새 판정을 기록할 수 없습니다.'))
            pending = outgoing - previous
            for record in pending:
                if (record.outgoing_approval_snapshot or
                        record.approval_request_id and record.approval_request_id.state != 'draft' or
                        record._name == 'iatf.process.inspection' and record.auto_evidence_snapshot):
                    raise UserError(_('기존 판정·상신 이력에 출하 판정 근거를 소급 추가하지 않습니다. 원본을 보존하고 새 검사로 검토하세요.'))
                if record.state != 'inspecting' or not record.result:
                    raise UserError(_('검사 시작 후 실제 결과를 입력하고 판정하십시오.'))
                if record._name == 'iatf.shipping.inspection':
                    results = [record[name] for name in ('visual_result', 'dimension_result', 'packaging_result', 'label_result')]
                    if not math.isfinite(record.quantity) or record.quantity <= 0 or any(not value for value in results):
                        raise UserError(_('양의 유한 출하 수량과 포장·라벨 등 실제 항목 판정이 필요합니다.'))
                    if record.result == 'pass' and 'fail' in results:
                        raise UserError(_('불합격 항목이 있는 포장·라벨 검사를 합격으로 판정할 수 없습니다.'))
            remaining = self - previous
            if remaining:
                super(OutgoingInspectionMixin, remaining).action_decide()
            for record in pending:
                record.with_context(_outgoing_snapshot_token=_SNAPSHOT_TOKEN).write({
                    'outgoing_decision_snapshot': {'version': 1, 'model': record._name, 'id': record.id,
                        'by': self.env.uid, 'at': fields.Datetime.to_string(fields.Datetime.now()),
                        'payload': record._outgoing_decision_payload()}})
            pending._assert_outgoing_decided()
        return True

    def _is_outgoing_inspection(self):
        self.ensure_one()
        return bool(self.picking_id) and (self._name == 'iatf.shipping.inspection' or self.inspection_stage == 'oqc')

    def _check_outgoing_identity(self):
        for record in self.filtered(lambda rec: rec._is_outgoing_inspection()):
            picking = record.picking_id
            if not picking or picking.picking_type_code != 'outgoing' or picking.company_id != record.company_id:
                raise UserError(_('출하검사는 같은 회사의 고객 출고 전표와 연결해야 합니다.'))
            if record.company_id not in self.env.companies:
                raise UserError(_('현재 허용 회사의 출하검사만 처리할 수 있습니다.'))
            if record.product_id.company_id and record.product_id.company_id != record.company_id:
                raise UserError(_('검사 제품의 회사가 다릅니다.'))
            if record.lot_id and (record.lot_id.product_id != record.product_id or
                    record.lot_id.company_id and record.lot_id.company_id != record.company_id):
                raise UserError(_('검사 제품·회사와 LOT가 일치하지 않습니다.'))
            if record.quantity_uom_id != record.product_id.uom_id:
                raise UserError(_('출하검사 수량은 제품 재고 단위로 기록해야 합니다.'))

    def _outgoing_payload(self):
        self.ensure_one()
        data = {'company_id': self.company_id.id, 'picking_id': self.picking_id.id,
                'partner_id': self.picking_id.partner_id.id, 'product_id': self.product_id.id,
                'lot_id': self.lot_id.id, 'uom_id': self.quantity_uom_id.id, 'result': self.result,
                'visual_result': self.visual_result, 'dimension_result': self.dimension_result}
        if self._name == 'iatf.process.inspection':
            data.update(stage=self.inspection_stage, inspection_type=self.inspection_type,
                quantity_produced=self.quantity_produced, quantity_inspected=self.quantity_inspected,
                quantity_accepted=self.quantity_accepted, quantity_rejected=self.quantity_rejected,
                function_result=self.function_result,
                lines=[{'id': line.id, 'characteristic_name': line.characteristic_name,
                        'specification': line.specification, 'measurement_method': line.measurement_method,
                        'measured_value': line.measured_value, 'result': line.result}
                       for line in self.line_ids.sorted('id')])
        else:
            specs = self.env['iatf.packaging.spec'].search([
                ('product_id', '=', self.product_id.id), ('state', '=', 'active'),
                ('company_id', 'in', (False, self.company_id.id)),
                ('customer_id', 'in', (False, self.picking_id.partner_id.id))])
            data.update(quantity=self.quantity, packaging_result=self.packaging_result,
                        label_result=self.label_result, partner_id=self.partner_id.id,
                        packaging_specs=[{'id': spec.id, 'write_date': str(spec.write_date)} for spec in specs.sorted('id')])
        linked = inspection_documents_snapshot(self)
        if linked:
            data['linked_evidence'] = linked
        return data

    def _validate_outgoing_result(self):
        self._check_outgoing_identity()
        self._assert_outgoing_decided()
        for record in self:
            if record.state not in ('decided', 'closed') or record.result != 'pass':
                raise UserError(_('출하 합격 판정 후 상신하세요. 보류·불합격·특채 근거 없는 조건부 합격은 출고할 수 없습니다.'))
            if record.product_id.tracking != 'none' and not record.lot_id:
                raise UserError(_('추적 제품의 출하검사에는 실제 LOT가 필요합니다.'))
            if record.lot_id and (record.lot_id.quality_hold or 'is_virtual' in record.lot_id._fields and record.lot_id.is_virtual):
                raise UserError(_('품질 보류·가상 LOT는 출하 승인할 수 없습니다.'))
            if record.lot_id and hasattr(record.lot_id, '_assert_injection_good_available'):
                record.lot_id._assert_injection_good_available()
            if record._name == 'iatf.process.inspection':
                if (record.inspection_type != 'full' or record.quantity_accepted <= 0 or
                        record.quantity_rejected != 0 or
                        abs(record.quantity_inspected - record.quantity_accepted) > 1e-9 or
                        abs(record.quantity_produced - record.quantity_accepted) > 1e-9):
                    raise UserError(_('현재 출고 gate는 전수검사 합격 수량만 지원합니다. 샘플링·특채는 승인 기준 연결이 필요합니다.'))
                if not record.line_ids or any(line.result != 'pass' or not line.measured_value for line in record.line_ids):
                    raise UserError(_('실측·관찰 결과가 기록된 합격 검사항목이 필요합니다.'))
                if any(record[name] == 'fail' for name in ('visual_result', 'dimension_result', 'function_result')):
                    raise UserError(_('항목별 불합격이 있는 검사는 출하 승인할 수 없습니다.'))
            else:
                if record.quantity <= 0 or record.partner_id != record.picking_id.partner_id:
                    raise UserError(_('포장·라벨 검사의 고객과 양의 수량을 확인하세요.'))
                if any(record[name] not in ('pass', 'na') for name in (
                        'visual_result', 'dimension_result', 'packaging_result', 'label_result')):
                    raise UserError(_('포장·라벨 등 각 항목을 합격 또는 승인 가능한 해당없음으로 판정하세요.'))
                if record._outgoing_payload()['packaging_specs'] and record.packaging_result != 'pass':
                    raise UserError(_('적용 포장사양이 있는 제품은 포장 합격이 필요합니다.'))

    def _assert_outgoing_approved(self):
        self._validate_outgoing_result()
        for record in self:
            record._approval_check_approved(_('고객 출고'))
            request = record.approval_request_id
            if request.res_model != record._name or request.res_id != record.id:
                raise UserError(_('다른 검사의 승인 근거를 사용할 수 없습니다.'))
            if not record.outgoing_approval_snapshot or record.outgoing_approval_snapshot != record._outgoing_payload():
                raise UserError(_('상신 당시 검사·LOT·수량·측정 기준이 변경되었습니다. 재판정 후 다시 상신하세요.'))
        return True

    def action_submit_approval(self):
        outgoing = self.filtered(lambda record: record._is_outgoing_inspection())
        outgoing.check_access('write')
        outgoing._validate_outgoing_result()
        if any(line.user_id == record.inspector_id for record in outgoing for line in record.approval_line_ids):
            raise UserError(_('출하검사는 검사자와 다른 결재자가 검토해야 합니다.'))
        for record in outgoing:
            record.with_context(_outgoing_snapshot_token=_SNAPSHOT_TOKEN).write({
                'outgoing_approval_snapshot': record._outgoing_payload()})
        return super().action_submit_approval()

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access('create')
        protected = {'outgoing_decision_snapshot', 'outgoing_decided_by_id', 'outgoing_decided_at'}
        if any(key in vals or 'default_' + key in self.env.context for vals in vals_list for key in protected):
            raise UserError(_('출하 판정 근거·사용자·시각은 판정 절차에서만 기록합니다.'))
        defaults = self.default_get(['product_id', 'outgoing_approval_snapshot', 'picking_id'])
        copied = [dict(defaults, **vals) for vals in vals_list]
        pickings = self.env['stock.picking'].browse([vals['picking_id'] for vals in copied if vals.get('picking_id')])
        outgoing = pickings.filtered(lambda picking: picking.picking_type_code == 'outgoing')
        if outgoing:
            outgoing.check_access('read')
        if any(picking.company_id not in self.env.companies for picking in outgoing):
            raise UserError(_('현재 허용 회사의 출하검사만 생성할 수 있습니다.'))
        # Creating a new inspection must serialize with shipment validation,
        # including the absence/duplicate-coverage decision. The caller has
        # inspection create + picking read; this only versions the picking row.
        outgoing.sudo()._lock_outgoing()
        for vals in copied:
            picking = self.env['stock.picking'].browse(vals.get('picking_id'))
            if picking.picking_type_code == 'outgoing' and picking.state == 'done':
                raise UserError(_('완료 출고에 검사 증빙을 소급 추가할 수 없습니다.'))
            if vals.get('outgoing_approval_snapshot'):
                raise UserError(_('출하검사 상신 근거를 직접 생성할 수 없습니다.'))
            product = self.env['product.product'].browse(vals.get('product_id'))
            vals.setdefault('quantity_uom_id', product.uom_id.id)
        with self.env.cr.savepoint():
            records = super().create(copied)
            records._check_outgoing_identity()
            validate_inspection_links(records.filtered(lambda row: row._is_outgoing_inspection()))
            return records

    def write(self, vals):
        outgoing = self.filtered(lambda record: record._is_outgoing_inspection())
        if 'state' in vals and outgoing.filtered('outgoing_decision_snapshot'):
            if vals['state'] not in ('decided', 'closed', 'cancelled') or any(
                    record.state == 'cancelled' and vals['state'] != 'cancelled'
                    for record in outgoing.filtered('outgoing_decision_snapshot')):
                raise UserError(_('판정 원검사를 초안·검사 중으로 되돌리거나 취소 후 되살릴 수 없습니다. 새 검사로 정정하세요.'))
        if 'outgoing_approval_snapshot' in vals and self.env.context.get('_outgoing_snapshot_token') is not _SNAPSHOT_TOKEN:
            raise UserError(_('출하검사 상신 근거를 직접 변경할 수 없습니다.'))
        if ({'outgoing_decision_snapshot', 'outgoing_decided_by_id', 'outgoing_decided_at'} & vals.keys()
                and self.env.context.get('_outgoing_snapshot_token') is not _SNAPSHOT_TOKEN):
            raise UserError(_('출하 판정 근거·사용자·시각은 직접 변경할 수 없습니다.'))
        if self.filtered(lambda record: record.picking_id.picking_type_code == 'outgoing' and
                         record.picking_id.state == 'done') and set(vals) - self._approval_reset_ignored_fields():
            raise UserError(_('출고 완료 검사는 변경할 수 없습니다. 별도 정정·반품 이력을 남기세요.'))
        with self.env.cr.savepoint():
            result = super().write(vals)
            self._check_outgoing_identity()
            if {'document_ids', 'attachment_ids', 'company_id', 'picking_id'} & vals.keys():
                validate_inspection_links(self.filtered(lambda row: row._is_outgoing_inspection()))
            if set(vals) - self._approval_reset_ignored_fields():
                self.filtered('outgoing_decision_snapshot')._assert_outgoing_decided()
            return result

    def unlink(self):
        if self.filtered(lambda record: record._is_outgoing_inspection() and
                         (record.picking_id.state == 'done' or record.outgoing_approval_snapshot or record.outgoing_decision_snapshot)):
            raise UserError(_('상신·출고 검사 이력은 삭제하지 않고 취소·재검사로 남기세요.'))
        return super().unlink()


class ProcessInspection(models.Model):
    _name = 'iatf.process.inspection'
    _inherit = ['iatf.outgoing.inspection.mixin', 'iatf.process.inspection']


class ShippingInspection(models.Model):
    _name = 'iatf.shipping.inspection'
    _inherit = ['iatf.outgoing.inspection.mixin', 'iatf.shipping.inspection']


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    def _approve_user(self, user):
        if self.res_model in ('iatf.process.inspection', 'iatf.shipping.inspection'):
            record = self._lock_workflow()
            if record._is_outgoing_inspection():
                if record.inspector_id == user:
                    raise UserError(_('검사자는 본인의 출하검사 결과를 승인할 수 없습니다.'))
                record._validate_outgoing_result()
                if not record.outgoing_approval_snapshot or record.outgoing_approval_snapshot != record._outgoing_payload():
                    raise UserError(_('상신 후 출하검사 또는 연결 자료가 변경되었습니다. 재검토 후 다시 상신하십시오.'))
        return super()._approve_user(user)


class ProcessInspectionLine(models.Model):
    _inherit = 'iatf.process.inspection.line'

    def _reset_outgoing_approval(self, inspections):
        outgoing = inspections.filtered(lambda record: record.inspection_stage == 'oqc')
        outgoing.check_access('write')
        if outgoing.filtered(lambda record: record.picking_id.state == 'done'):
            raise UserError(_('출고 완료 검사의 측정 증빙은 변경할 수 없습니다.'))
        for record in outgoing.filtered('outgoing_approval_snapshot'):
            record.with_context(_outgoing_snapshot_token=_SNAPSHOT_TOKEN).write({'outgoing_approval_snapshot': False})

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['inspection_id'])
        inspection_ids = [dict(defaults, **vals).get('inspection_id') for vals in vals_list]
        inspections = self.env['iatf.process.inspection'].browse([value for value in inspection_ids if value])
        self._reset_outgoing_approval(inspections)
        return super().create(vals_list)

    def write(self, vals):
        inspections = self.inspection_id | self.env['iatf.process.inspection'].browse(vals.get('inspection_id'))
        self._reset_outgoing_approval(inspections)
        return super().write(vals)

    def unlink(self):
        self._reset_outgoing_approval(self.inspection_id)
        return super().unlink()
