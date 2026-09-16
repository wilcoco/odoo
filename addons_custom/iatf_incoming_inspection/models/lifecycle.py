"""LOT-bound inspection evidence and separately authorized exception release."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero
from math import isfinite

_LIFECYCLE = object()
_OWNED = {'hold_version', 'decision_snapshot', 'decision_history', 'source_move_id', 'disposal_move_id',
          'release_requested', 'released_version', 'released_by', 'released_at'}
_IDENTITY = {'lot_id', 'product_id', 'company_id', 'picking_id', 'quantity_received', 'supplier_id'}
_EVIDENCE = _IDENTITY | {'quantity_inspected', 'quantity_accepted', 'quantity_rejected',
    'result', 'disposition', 'inspection_type', 'sampling_plan', 'sample_size', 'accept_number',
    'reject_number', 'visual_result', 'dimension_result', 'material_result', 'supplier_cert_no',
    'notes', 'line_ids', 'document_ids', 'attachment_ids', 'inspection_date', 'inspector_id'}


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    @api.model
    def _approval_management_roles(self):
        return dict(super()._approval_management_roles(), **{
            'iatf.incoming.inspection': 'iatf_incoming_inspection.group_incoming_inspection_user'})


class IncomingInspection(models.Model):
    _inherit = 'iatf.incoming.inspection'

    source_move_id = fields.Many2one('stock.move', readonly=True, copy=False, ondelete='restrict', index=True)
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='수량 단위')
    hold_version = fields.Integer(string='검사 근거 보류 버전', readonly=True, copy=False)
    decision_snapshot = fields.Json(string='판정 당시 근거', readonly=True, copy=False)
    decision_history = fields.Json(string='과거 판정 근거', readonly=True, copy=False)
    disposal_move_id = fields.Many2one('stock.move', string='불합격 처분 이동', readonly=True, copy=False, ondelete='restrict')
    disposition = fields.Selection(selection_add=[('scrap', '폐기')], ondelete={'scrap': 'set null'})
    release_reviewer_id = fields.Many2one('res.users', string='품질 검토자')
    release_approver_id = fields.Many2one('res.users', string='생산 승인자')
    release_executor_id = fields.Many2one('res.users', string='최종 해제 담당자')
    release_reason = fields.Text(string='예외 해제 근거')
    release_requested = fields.Boolean(readonly=True, copy=False, string='예외 해제 상신')
    released_version = fields.Integer(readonly=True, copy=False, string='해제 보류 버전')
    released_by = fields.Many2one('res.users', readonly=True, copy=False, string='해제 처리자')
    released_at = fields.Datetime(readonly=True, copy=False, string='해제 시각')

    def _internal(self):
        return self.with_context(_iqc_lifecycle=_LIFECYCLE)

    def _approval_reset_ignored_fields(self):
        return super()._approval_reset_ignored_fields() | _OWNED | {'state', 'nonconformity_id'}

    def _approval_lock(self):
        self.lot_id.sudo()._lock_quality()
        return super()._approval_lock()

    @api.model_create_multi
    def create(self, vals_list):
        internal = self.env.context.get('_iqc_lifecycle') is _LIFECYCLE
        if not internal and any(set(v) & _OWNED or v.get('state', 'draft') != 'draft' for v in vals_list):
            raise AccessError(_('검사 근거와 판정 상태는 서버에서 관리합니다.'))
        defaults = self.default_get(['lot_id'])
        values = []
        for vals in vals_list:
            lot = self.env['stock.lot'].browse(vals.get('lot_id', defaults.get('lot_id')))
            lot._lock_quality()
            values.append(dict(vals, state='draft', hold_version=lot.hold_version if lot else 0,
                               decision_snapshot=False, decision_history=[], release_requested=False, released_version=0,
                               released_by=False, released_at=False, disposal_move_id=False))
        return super().create(values)

    @api.model
    def default_get(self, names):
        vals = super().default_get(names)
        for key in _OWNED | {'state'}:
            vals.pop(key, None)
        return vals

    def write(self, vals):
        internal = self.env.context.get('_iqc_lifecycle') is _LIFECYCLE
        if not internal and set(vals) & (_OWNED | {'state'}):
            raise AccessError(_('판정·해제 상태와 근거는 전용 동작으로만 변경할 수 있습니다.'))
        if not internal and set(vals) & _IDENTITY and any(r.source_move_id or r.state != 'draft' for r in self):
            raise UserError(_('입고에 연결되거나 판정한 검사의 LOT·수량·회사는 변경할 수 없습니다. 새 검사를 사용하세요.'))
        if not internal and set(vals) & _EVIDENCE:
            self._approval_lock()
            self._invalidate_quality_evidence()
        return super().write(dict(vals))

    def unlink(self):
        if any(r.source_move_id or r.decision_snapshot or r.released_at for r in self):
            raise UserError(_('입고·판정·해제 근거가 있는 검사는 삭제할 수 없습니다.'))
        return super().unlink()

    def _invalidate_quality_evidence(self):
        for rec in self.filtered(lambda r: r.state in ('decided', 'closed')):
            if rec.disposal_move_id:
                raise UserError(_('처분 이동이 완료된 검사 근거는 수정할 수 없습니다. 새 검사를 작성하세요.'))
            if rec.lot_id:
                rec.lot_id.sudo()._place_iqc_hold(_('검사 근거 변경: %s') % rec.name)
            if rec.approval_state in ('approved', 'in_progress'):
                rec.action_reset_approval()
            rec._internal().write({'state': 'inspecting', 'decision_snapshot': False,
                                  'release_requested': False, 'hold_version': rec.lot_id.hold_version})

    def _evidence(self):
        self.ensure_one()
        return {**{key: self[key].id if self._fields[key].type == 'many2one' else self[key]
                   for key in sorted(_EVIDENCE - {'line_ids', 'document_ids', 'attachment_ids', 'inspection_date'})},
                'inspection_date': str(self.inspection_date), 'hold_version': self.hold_version,
                'document_ids': [[d.id, str(d.write_date)] for d in self.document_ids],
                'attachment_ids': [[a.id, a.checksum] for a in self.attachment_ids],
                'lines': self.line_ids.read(['sequence', 'characteristic_name', 'characteristic_type',
                    'specification', 'measurement_method', 'measured_value', 'result', 'notes'])}

    def _approval_snapshot(self):
        self.ensure_one()
        return {'inspection': self._evidence(), 'hold_reason': self.lot_id.hold_reason,
                'reviewer': self.release_reviewer_id.id, 'approver': self.release_approver_id.id,
                'executor': self.release_executor_id.id, 'reason': self.release_reason,
                'disposal_move': self.disposal_move_id.id,
                'disposal_date': str(self.disposal_move_id.write_date)}

    def _check_scope_quantities(self):
        self.ensure_one()
        if self.company_id not in self.env.companies or (self.lot_id and (
                self.product_id != self.lot_id.product_id or self.company_id != self.lot_id.company_id)):
            raise UserError(_('검사와 LOT의 품목·허용 회사를 확인해 주세요.'))
        rounding = self.product_id.uom_id.rounding
        if self.source_move_id:
            move = self.source_move_id.sudo()
            actual = sum(line.product_uom_id._compute_quantity(line.quantity, self.product_id.uom_id, round=False)
                         for line in move.move_line_ids if line.lot_id == self.lot_id)
            if move.state != 'done' or move.product_id != self.product_id or move.company_id != self.company_id or move.picking_id != self.picking_id or float_compare(actual, self.quantity_received, precision_rounding=rounding):
                raise ValidationError(_('완료 입고의 LOT별 실제 수량과 검사 범위가 다릅니다.'))
        quantities = [self.quantity_received, self.quantity_inspected, self.quantity_accepted, self.quantity_rejected]
        if any(not isfinite(q) or q < 0 for q in quantities) or self.quantity_received <= 0 or self.quantity_inspected <= 0:
            raise ValidationError(_('입고·검사 수량은 양수이며 합격·불합격 수량은 음수일 수 없습니다.'))
        if float_compare(self.quantity_inspected, self.quantity_received, precision_rounding=rounding) > 0:
            raise ValidationError(_('검사 수량은 입고 수량을 초과할 수 없습니다.'))
        if float_compare(self.quantity_accepted + self.quantity_rejected, self.quantity_received, precision_rounding=rounding) > 0:
            raise ValidationError(_('합격·불합격 수량 합계는 입고 수량을 초과할 수 없습니다.'))

    def action_start_inspection(self):
        self.check_access('write')
        self._approval_lock()
        for rec in self:
            if rec.state not in ('draft', 'inspecting'):
                raise UserError(_('판정한 검사는 근거를 수정하거나 새 검사를 작성해 주세요.'))
            rec._internal().write({'state': 'inspecting', 'hold_version': rec.lot_id.hold_version})
        return True

    def action_decide(self):
        self.check_access('write')
        self._approval_lock()
        for rec in self:
            if rec.state in ('decided', 'closed'):
                rec._check_release_evidence(require_eligible=False)
                continue
            if rec.state not in ('draft', 'inspecting') or not rec.result:
                raise UserError(_('검사 중인 문서에 판정 결과를 입력해 주세요.'))
            if rec.lot_id and rec.hold_version != rec.lot_id.hold_version:
                raise UserError(_('새 보류가 발생했습니다. 검사 시작으로 현재 보류를 확인하고 재검사해 주세요.'))
            if not rec.quantity_accepted and not rec.quantity_rejected:
                rec._internal().write({'quantity_accepted': rec.quantity_received if rec.result == 'pass' else 0,
                                       'quantity_rejected': rec.quantity_received if rec.result == 'fail' else 0})
            rec._check_scope_quantities()
            if rec.result == 'pass' and (rec.quantity_rejected or rec.quantity_accepted != rec.quantity_received):
                raise ValidationError(_('합격 판정은 전량 합격일 때만 사용할 수 있습니다. 부분 판정은 조건부 합격을 사용하세요.'))
            if rec.result == 'fail' and rec.quantity_accepted:
                raise ValidationError(_('불합격 판정에는 합격 수량을 지정할 수 없습니다.'))
            if rec.result == 'pass' and rec.line_ids.filtered(lambda l: l.result == 'fail'):
                raise ValidationError(_('불합격 검사 항목이 있으면 전량 합격으로 판정할 수 없습니다.'))
            evidence = rec._evidence()
            rec._internal().write({'state': 'decided', 'decision_snapshot': evidence,
                'decision_history': (rec.decision_history or []) + [{'at': str(fields.Datetime.now()), 'by': self.env.uid, 'evidence': evidence}]})
            if rec.result == 'fail':
                # A verdict never silently scraps all quants of this LOT.
                rec.sudo().with_company(rec.company_id)._auto_create_nc()
            if rec.lot_id and rec.lot_id.quality_hold and rec.result == 'pass' and rec.lot_id.hold_origin == 'iqc' and rec.disposition in (False, 'accept'):
                if not rec._other_unresolved_inspections():
                    rec._release_quality_hold()
        return True

    def _other_unresolved_inspections(self):
        self.ensure_one()
        others = self.sudo().search([('lot_id', '=', self.lot_id.id), ('company_id', '=', self.company_id.id),
                                    ('id', '!=', self.id), ('state', '!=', 'cancelled')])
        return others.filtered(lambda r: r.state not in ('decided', 'closed') or not r.decision_snapshot
            or r.decision_snapshot != r._evidence() or not r._quantity_resolved())

    def _quantity_resolved(self):
        self.ensure_one()
        disposed = 0
        move = self.disposal_move_id
        if move and move.state == 'done' and move.product_id == self.product_id and move.company_id == self.company_id:
            disposed = sum(l.product_uom_id._compute_quantity(l.quantity, self.product_id.uom_id, round=False)
                           for l in move.move_line_ids if l.lot_id == self.lot_id)
        accepted = self.quantity_accepted if self.result in ('pass', 'conditional') and self.disposition in (False, 'accept', 'concession', 'return', 'scrap') else 0
        return float_is_zero(self.quantity_received - accepted - disposed,
                             precision_rounding=self.product_id.uom_id.rounding)

    def _check_release_evidence(self, require_eligible=True):
        self.ensure_one()
        self._check_scope_quantities()
        if self.state not in ('decided', 'closed') or not self.decision_snapshot or self.decision_snapshot != self._evidence():
            raise UserError(_('현재 검사 내용과 판정 근거가 다릅니다. 다시 판정해 주세요.'))
        if self.lot_id and self.hold_version != self.lot_id.hold_version:
            raise UserError(_('현재 보류 버전과 검사 근거가 다릅니다. 이전 판정으로 새 보류를 해제할 수 없습니다.'))
        if require_eligible:
            if self.result not in ('pass', 'conditional') or self.disposition not in (False, 'accept', 'concession', 'return', 'scrap') or not self._quantity_resolved() or self._other_unresolved_inspections():
                raise UserError(_('이 LOT에 미판정·불합격·미처분 수량이 남아 있어 전체 해제할 수 없습니다.'))
            if self.result != 'pass' or self.lot_id.hold_origin != 'iqc':
                self._approval_check_approved(_('예외 품질 보류 해제'))
                if not self.release_requested or self.approval_request_id.snapshot != self._approval_snapshot() or self.env.user != self.release_executor_id:
                    raise UserError(_('현재 근거의 예외 해제 승인과 지정 해제 담당자가 필요합니다.'))
        return True

    def _release_quality_hold(self):
        self.ensure_one()
        if self.lot_id and self.lot_id.quality_hold:
            self.lot_id.sudo()._release_quality_hold_from_iqc(self)
            self._internal().write({'released_version': self.hold_version, 'released_by': self.env.uid,
                                    'released_at': fields.Datetime.now()})
            self.message_post(body=_('LOT %s 보류 버전 %s 해제') % (self.lot_id.name, self.hold_version))

    def _check_release_roles(self):
        self.ensure_one()
        reviewer, approver, executor = self.release_reviewer_id, self.release_approver_id, self.release_executor_id
        if not self.release_reason or not reviewer or not approver or not executor or reviewer == approver:
            raise UserError(_('해제 사유, 서로 다른 품질 검토자·생산 승인자, 최종 해제 담당자를 지정해 주세요.'))
        for user, group in [(reviewer, 'iatf_incoming_inspection.group_quality_release_reviewer'),
                            (approver, 'iatf_incoming_inspection.group_quality_release_approver'),
                            (executor, 'iatf_incoming_inspection.group_quality_release_executor')]:
            if not user.active or user.share or self.company_id not in user.company_ids or not user.has_group(group):
                raise UserError(_('지정 담당자의 역할·회사·활성 상태를 확인해 주세요.'))

    def action_request_release(self):
        self.check_access('write')
        self._approval_lock()
        for rec in self:
            rec._check_release_evidence(require_eligible=False)
            rec._check_release_roles()
            if not rec.lot_id.quality_hold:
                raise UserError(_('현재 보류 중인 LOT만 해제를 상신할 수 있습니다.'))
            if rec.approval_state != 'draft':
                rec.action_reset_approval()
            rec.approval_request_id.write({'line_ids': [(5, 0, 0),
                (0, 0, {'sequence': 1, 'user_id': rec.release_reviewer_id.id}),
                (0, 0, {'sequence': 2, 'user_id': rec.release_approver_id.id})]})
            rec._internal().write({'release_requested': True})
            rec.action_submit_approval()
        return True

    def _approval_validate_submit(self):
        super()._approval_validate_submit()
        for rec in self.filtered('release_requested'):
            rec._check_release_roles()
            rec._check_release_evidence(require_eligible=False)
            lines = rec.approval_request_id.line_ids.sorted(lambda l: (l.sequence, l.id))
            if lines.mapped('user_id').ids != [rec.release_reviewer_id.id, rec.release_approver_id.id] or len(lines) != 2:
                raise UserError(_('예외 해제는 품질 검토→생산 승인 두 단계여야 합니다.'))

    def action_release_hold(self):
        self.check_access('write')
        self._approval_lock()
        for rec in self:
            rec._check_release_roles()
            if not rec.lot_id.quality_hold and rec.released_by == self.env.user and rec.released_version == rec.hold_version == rec.lot_id.hold_version:
                continue
            rec._approval_check_approved(_('예외 품질 보류 해제'))
            if not rec.release_requested or rec.env.user != rec.release_executor_id or rec.approval_request_id.snapshot != rec._approval_snapshot():
                raise UserError(_('현재 근거의 승인을 받은 지정 담당자만 해제할 수 있습니다.'))
            rec._check_release_evidence()
            rec._release_quality_hold()
        return True

    def action_close(self):
        self.check_access('write')
        if any(rec.state != 'decided' for rec in self):
            raise UserError(_('판정 완료한 검사만 종료할 수 있습니다.'))
        return self._internal().write({'state': 'closed'})

    def action_process_disposition(self):
        """Explicit stock movement of this receipt/LOT's rejected quantity only."""
        self.check_access('write')
        self._approval_lock()
        for rec in self:
            rec._check_release_evidence(require_eligible=False)
            if rec.disposal_move_id:
                continue
            if rec.disposition not in ('return', 'scrap') or rec.quantity_rejected <= 0 or not rec.source_move_id or not rec.lot_id:
                raise UserError(_('입고 LOT과 불합격 수량을 확인하고 반품 또는 폐기를 선택해 주세요.'))
            origin = rec.source_move_id
            if origin.state != 'done' or origin.company_id != rec.company_id or origin.product_id != rec.product_id:
                raise UserError(_('원 입고 이동과 검사 범위가 일치하지 않습니다.'))
            location = origin.location_dest_id
            available = self.env['stock.quant']._get_available_quantity(rec.product_id, location, lot_id=rec.lot_id, strict=True)
            if float_compare(available, rec.quantity_rejected, precision_rounding=rec.product_id.uom_id.rounding) < 0:
                raise UserError(_('원 입고 위치의 이 LOT 가용 수량이 부족합니다. 예약·소유자·위치를 확인해 주세요.'))
            dest = origin.location_id if rec.disposition == 'return' else self.env['stock.location'].search([
                ('scrap_location', '=', True), ('company_id', 'in', [False, rec.company_id.id])], limit=1)
            if not dest or (rec.disposition == 'return' and dest.usage != 'supplier'):
                raise UserError(_('회사에 맞는 반품/폐기 위치가 필요합니다.'))
            move = self.env['stock.move'].create({
                'name': _('IQC %s: %s') % (rec.disposition, rec.name), 'company_id': rec.company_id.id,
                'product_id': rec.product_id.id, 'product_uom': rec.product_id.uom_id.id,
                'product_uom_qty': rec.quantity_rejected, 'location_id': location.id,
                'location_dest_id': dest.id, 'origin': rec.name,
                'origin_returned_move_id': origin.id if rec.disposition == 'return' else False,
            })
            move._action_confirm()
            self.env['stock.move.line'].create({'move_id': move.id, 'product_id': rec.product_id.id,
                'product_uom_id': rec.product_id.uom_id.id, 'lot_id': rec.lot_id.id,
                'quantity': rec.quantity_rejected, 'picked': True,
                'location_id': location.id, 'location_dest_id': dest.id})
            move.picked = True
            move._action_done()
            rec._internal().write({'disposal_move_id': move.id})
            rec.message_post(body=_('불합격 수량 %s %s 처분 완료: %s') % (rec.quantity_rejected, rec.product_uom_id.name, move.id))
        return True

    def action_cancel(self):
        self.check_access('write')
        if not self.env.user.has_group('iatf_incoming_inspection.group_incoming_inspection_manager'):
            raise AccessError(_('검사 취소는 수입검사 관리자가 처리해 주세요.'))
        if any(rec.disposal_move_id for rec in self):
            raise UserError(_('처분 이동이 있는 검사는 취소할 수 없습니다.'))
        self._approval_lock()
        for rec in self:
            rec.lot_id.sudo().write({'quality_hold': True, 'hold_reason': _('검사 취소: %s') % rec.name})
        return self._internal().write({'state': 'cancelled'})

    def _auto_quarantine_lot(self):
        """Keep physical disposition explicit; never substitute a scrap location for quarantine."""
        return False


class IncomingInspectionLine(models.Model):
    _inherit = 'iatf.incoming.inspection.line'

    @api.model_create_multi
    def create(self, vals_list):
        default = self.default_get(['inspection_id']).get('inspection_id')
        parents = self.env['iatf.incoming.inspection'].browse([v.get('inspection_id', default) for v in vals_list if v.get('inspection_id', default)])
        parents.check_access('write')
        parents._approval_lock()
        parents._invalidate_quality_evidence()
        return super().create(vals_list)

    def write(self, vals):
        parents = self.inspection_id | self.env['iatf.incoming.inspection'].browse(vals.get('inspection_id', []))
        parents.check_access('write')
        parents._approval_lock()
        parents._invalidate_quality_evidence()
        return super().write(vals)

    def unlink(self):
        parents = self.inspection_id
        parents.check_access('write')
        parents._approval_lock()
        parents._invalidate_quality_evidence()
        return super().unlink()
