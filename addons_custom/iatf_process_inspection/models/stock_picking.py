from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import SQL


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    oqc_inspection_ids = fields.One2many('iatf.process.inspection', 'picking_id', string='출하검사')
    oqc_count = fields.Integer(compute='_compute_oqc_count')
    outgoing_shipping_inspection_ids = fields.One2many(
        'iatf.shipping.inspection', 'picking_id', string='포장·라벨 검사')

    def _compute_oqc_count(self):
        for picking in self:
            picking.oqc_count = len(picking.oqc_inspection_ids)

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['picking_type_id', 'state'])
        for vals in vals_list:
            effective = dict(defaults, **vals)
            kind = self.env['stock.picking.type'].browse(effective.get('picking_type_id'))
            if kind.code == 'outgoing' and effective.get('state') == 'done':
                raise UserError(_('출고 완료는 검사·재고 검증 절차로만 처리합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        completed = self.filtered(lambda picking: picking.picking_type_code == 'outgoing' and picking.state == 'done')
        identity = {'partner_id', 'company_id', 'picking_type_id', 'location_id', 'location_dest_id', 'origin', 'state'}
        if completed and identity.intersection(vals):
            raise UserError(_('완료 출고의 거래처·유형·출처는 변경할 수 없습니다. 별도 정정 이력을 남기세요.'))
        if vals.get('state') == 'done' and self.filtered(lambda picking: picking.picking_type_code == 'outgoing'):
            raise UserError(_('출고 완료 상태를 직접 지정할 수 없습니다.'))
        return super().write(vals)

    def _lock_outgoing(self):
        self.check_access('write')
        for picking in self.sorted('id'):
            # A tuple-version change makes concurrent REPEATABLE READ requests
            # retry rather than inspect a stale approval/stock snapshot.
            self.env.cr.execute('UPDATE stock_picking SET write_date = write_date WHERE id = %s', [picking.id])
        self.invalidate_recordset(['state', 'move_ids', 'oqc_inspection_ids', 'outgoing_shipping_inspection_ids'])

    def _outgoing_requirements(self, moves=None):
        self.ensure_one()
        if self.company_id not in self.env.companies:
            raise UserError(_('현재 허용 회사의 출고만 처리할 수 있습니다.'))
        if not self.partner_id:
            raise UserError(_('출고 거래처를 먼저 지정하세요.'))
        requirements = defaultdict(float)
        moves = moves if moves is not None else self.move_ids
        for move in moves.filtered(lambda record: record.state != 'cancel'):
            if move.company_id != self.company_id:
                raise UserError(_('출고와 재고 이동 회사가 다릅니다.'))
            used = 0.0
            for line in move.move_line_ids:
                quantity = line.product_uom_id._compute_quantity(line.quantity, move.product_id.uom_id, round=False)
                if quantity < 0:
                    raise UserError(_('음수 출고 수량은 사용할 수 없습니다.'))
                if not quantity:
                    continue
                if line.company_id != self.company_id or line.product_id != move.product_id:
                    raise UserError(_('출고 상세의 회사·제품이 다릅니다.'))
                lot = line.lot_id
                if move.product_id.tracking != 'none' and not lot:
                    raise UserError(_('실제 출고 LOT를 먼저 지정하세요.'))
                if lot and (lot.product_id != move.product_id or lot.company_id and lot.company_id != self.company_id):
                    raise UserError(_('출고 제품·회사와 LOT가 일치하지 않습니다.'))
                if lot and (lot.quality_hold or 'is_virtual' in lot._fields and lot.is_virtual):
                    raise UserError(_('품질 보류 또는 가상 LOT는 출고할 수 없습니다.'))
                requirements[(move.product_id.id, lot.id or False, move.product_id.uom_id.id)] += quantity
                used += quantity
            planned = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id, round=False)
            if used > planned + 1e-9:
                raise UserError(_('출고 지시 수량보다 많이 출고할 수 없습니다.'))
        if not requirements:
            raise UserError(_('출고할 LOT와 실제 수량을 먼저 입력하세요.'))
        return dict(requirements)

    def action_prepare_oqc(self):
        """Persist draft inspections before a later validation request."""
        for picking in self:
            if picking.picking_type_code != 'outgoing' or picking.state in ('done', 'cancel'):
                raise UserError(_('미완료 고객 출고에서만 검사를 준비할 수 있습니다.'))
            if picking._is_iqc_supplier_return():
                raise UserError(_('수입검사 반품은 해당 IQC의 불합격 처분과 승인으로 처리합니다.'))
            picking._lock_outgoing()
            requirements = picking._outgoing_requirements()
            for (product_id, lot_id, uom_id), quantity in requirements.items():
                active = picking.oqc_inspection_ids.filtered(lambda record: record.state != 'cancelled' and
                    record.inspection_stage == 'oqc' and record.product_id.id == product_id and
                    (record.lot_id.id or False) == lot_id)
                if not active:
                    self.env['iatf.process.inspection'].sudo().with_company(picking.company_id).create({
                        'inspection_stage': 'oqc', 'inspection_type': 'full', 'picking_id': picking.id,
                        'product_id': product_id, 'lot_id': lot_id, 'quantity_uom_id': uom_id,
                        'quantity_produced': quantity, 'quantity_inspected': 0,
                        'company_id': picking.company_id.id, 'inspector_id': False})
                shipping = picking.outgoing_shipping_inspection_ids.filtered(lambda record: record.state != 'cancelled' and
                    record.product_id.id == product_id and (record.lot_id.id or False) == lot_id)
                if not shipping:
                    self.env['iatf.shipping.inspection'].sudo().with_company(picking.company_id).create({
                        'picking_id': picking.id, 'product_id': product_id, 'lot_id': lot_id,
                        'quantity': quantity, 'quantity_uom_id': uom_id, 'partner_id': picking.partner_id.id,
                        'company_id': picking.company_id.id, 'inspector_id': False})
        return self.action_view_oqc() if len(self) == 1 else True

    def _is_iqc_supplier_return(self):
        """Only immutable IQC return moves can use their own disposition gate."""
        self.ensure_one()
        moves = self.move_ids.filtered(lambda move: move.state != 'cancel')
        return bool(moves and self.location_dest_id.usage == 'supplier' and all(
            move.iqc_inspection_id and move.iqc_movement_kind == 'return'
            and move.origin_returned_move_id and move.location_dest_id.usage == 'supplier'
            for move in moves))

    def _assert_outgoing_inspections(self, moves=None):
        for picking in self.filtered(lambda rec: rec.picking_type_code == 'outgoing'):
            # IQC rejection returns may share the warehouse's outgoing type.
            # Revalidate their own approval, source, quantities and destination;
            # a supplier destination alone must never bypass the shipment gate.
            if picking._is_iqc_supplier_return():
                for move in picking.move_ids.filtered(lambda record: record.state != 'cancel'):
                    move.iqc_inspection_id._iqc_validate_movement(move)
                continue
            # Freeze every existing row used by the decision. A version update
            # also makes a concurrent editor retry its old REPEATABLE READ
            # snapshot and then observe the posted picking's immutable state.
            move_scope = moves if moves is not None else picking.move_ids
            inspections = picking.oqc_inspection_ids
            shipping = picking.outgoing_shipping_inspection_ids
            specs = self.env['iatf.packaging.spec'].search([
                ('product_id', 'in', move_scope.product_id.ids), ('state', '=', 'active'),
                ('company_id', 'in', (False, picking.company_id.id)),
                ('customer_id', 'in', (False, picking.partner_id.id))])
            scopes = (move_scope, move_scope.move_line_ids, move_scope.move_line_ids.lot_id,
                      inspections, inspections.line_ids, shipping, specs)
            for records in scopes:
                if not records:
                    continue
                records.check_access('read')
                records.flush_recordset()
                self.env.cr.execute(SQL('UPDATE %s SET write_date = write_date WHERE id IN %s',
                    SQL.identifier(records._table), tuple(sorted(records.ids))))
                records.invalidate_recordset()
            requirements = picking._outgoing_requirements(moves)
            for inspections in (picking.oqc_inspection_ids.filtered(
                    lambda row: row.inspection_stage == 'oqc' and row.state != 'cancelled'),
                    picking.outgoing_shipping_inspection_ids.filtered(lambda row: row.state != 'cancelled')):
                approved = defaultdict(float)
                if not inspections:
                    raise UserError(_('출하검사와 포장·라벨 검사를 준비하고 승인받으세요.'))
                for inspection in inspections:
                    inspection._assert_outgoing_approved()
                    key = (inspection.product_id.id, inspection.lot_id.id or False, inspection.quantity_uom_id.id)
                    if key in approved:
                        raise UserError(_('같은 LOT의 활성 출하검사가 중복되었습니다. 기존 검사를 취소하고 재검사하세요.'))
                    approved[key] = inspection.quantity_accepted if inspection._name == 'iatf.process.inspection' else inspection.quantity
                if set(approved) != set(requirements) or any(
                        abs(approved[key] - quantity) > 1e-9 for key, quantity in requirements.items()):
                    raise UserError(_('승인된 검사와 실제 출고 제품·LOT·수량·단위가 다릅니다. 변경 범위를 재검사하세요.'))
        return True

    def button_validate(self):
        pending = self.filtered(lambda rec: rec.picking_type_code == 'outgoing' and rec.state not in ('done', 'cancel'))
        pending._lock_outgoing()
        pending._assert_outgoing_inspections()
        return super().button_validate()

    def _create_oqc_inspections(self):
        # Backwards-compatible internal entry point, now explicitly called before validation.
        return self.action_prepare_oqc()

    def action_view_oqc(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'iatf.process.inspection',
                'view_mode': 'list,form', 'domain': [('picking_id', '=', self.id)],
                'name': _('출하검사'), 'context': {'default_picking_id': self.id, 'default_inspection_stage': 'oqc'}}

    def action_view_shipping_inspections(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'iatf.shipping.inspection',
                'view_mode': 'list,form', 'domain': [('picking_id', '=', self.id)],
                'name': _('포장·라벨 검사'), 'context': {'default_picking_id': self.id}}
