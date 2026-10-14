from collections import defaultdict

from odoo import api, models, _
from odoo.exceptions import UserError


_OUTGOING_POST_TOKEN = object()


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _assert_assembly_outgoing_stock(self):
        """Physical stock guard limited to known MES assembly products."""
        if 'is_jr' not in self.env['mrp.production']._fields:
            return True
        requirements = defaultdict(float)
        own_reserved = defaultdict(float)
        for move in self:
            assembly = self.env['mrp.production'].sudo().search_count([
                ('product_id', '=', move.product_id.id), ('company_id', '=', move.company_id.id), ('is_jr', '=', True)], limit=1)
            if not assembly or not move.product_id.is_storable:
                continue
            for line in move.move_line_ids.filtered(lambda row: row.quantity > 0):
                if line.location_id.usage != 'internal':
                    raise UserError(_('조립제품 고객 출고는 실제 내부 재고 위치에서 처리해야 합니다.'))
                key = (move.product_id, line.location_id, line.lot_id, line.package_id, line.owner_id)
                quantity = line.product_uom_id._compute_quantity(line.quantity, move.product_id.uom_id, round=False)
                requirements[key] += quantity
                if move.state not in ('done', 'cancel'):
                    own_reserved[key] += quantity
        Quant = self.env['stock.quant'].sudo()
        quants_by_key = {key: Quant._gather(key[0], key[1], lot_id=key[2], package_id=key[3], owner_id=key[4], strict=True)
                         for key in requirements}
        all_quants = Quant.browse()
        for quants in quants_by_key.values():
            all_quants |= quants
        if all_quants:
            self.env.cr.execute('SELECT id FROM stock_quant WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(all_quants.ids)])
            all_quants.invalidate_recordset(['quantity', 'reserved_quantity'])
        for key, needed in requirements.items():
            quants = quants_by_key[key]
            physical = sum(quants.mapped('quantity'))
            foreign = self.env['stock.move.line'].sudo().search([
                ('move_id', 'not in', self.ids), ('state', 'not in', ('done', 'cancel')),
                ('product_id', '=', key[0].id), ('location_id', '=', key[1].id),
                ('lot_id', '=', key[2].id or False), ('package_id', '=', key[3].id or False),
                ('owner_id', '=', key[4].id or False)])
            foreign_quantity = sum(line.product_uom_id._compute_quantity(
                line.quantity, key[0].uom_id, round=False) for line in foreign)
            foreign_reservation = max(foreign_quantity, sum(quants.mapped('reserved_quantity')) - own_reserved[key], 0)
            available = physical - foreign_reservation
            if min(physical, available) + 1e-9 < needed:
                raise UserError(_('조립제품의 실재고가 부족하거나 다른 출고에 예약되어 있습니다: %s') % key[0].display_name)
        return True

    def _action_done(self, cancel_backorder=False):
        outgoing = self.filtered(lambda move: move.picking_id.picking_type_code == 'outgoing' and move.state not in ('done', 'cancel'))
        for picking in outgoing.picking_id.sorted('id'):
            picking._lock_outgoing()
            # Validate the entire shipment even when a custom caller posts only
            # one move, so unapproved components cannot hide in another batch.
            picking._assert_outgoing_inspections()
        outgoing._assert_assembly_outgoing_stock()
        return super(StockMove, self.with_context(_outgoing_post_token=_OUTGOING_POST_TOKEN))._action_done(
            cancel_backorder=cancel_backorder)

    def _has_outgoing_evidence(self):
        return bool(self.filtered(lambda move: move.state == 'done' and move.picking_id.picking_type_code == 'outgoing'))

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_outgoing_post_token') is not _OUTGOING_POST_TOKEN:
            defaults = self.default_get(['picking_id', 'state'])
            for vals in vals_list:
                effective = dict(defaults, **vals)
                picking = self.env['stock.picking'].browse(effective.get('picking_id'))
                if picking.picking_type_code == 'outgoing' and (picking.state == 'done' or effective.get('state') == 'done'):
                    raise UserError(_('완료 출고의 재고 이동을 직접 생성할 수 없습니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get('_outgoing_post_token') is not _OUTGOING_POST_TOKEN:
            evidence = {'state', 'product_id', 'product_uom', 'product_uom_qty', 'quantity',
                        'move_line_ids', 'lot_ids', 'picking_id', 'location_id', 'location_dest_id', 'company_id', 'picked'}
            if evidence.intersection(vals) and self._has_outgoing_evidence():
                raise UserError(_('완료 출고의 재고 근거는 수정할 수 없습니다. 별도 반품·정정 이동을 사용하세요.'))
            destination = self.env['stock.picking'].browse(vals.get('picking_id'))
            if destination.picking_type_code == 'outgoing' and destination.state == 'done':
                raise UserError(_('기존 재고 이동을 완료 출고에 연결할 수 없습니다.'))
            if vals.get('state') == 'done' and self.filtered(lambda move: move.picking_id.picking_type_code == 'outgoing'):
                raise UserError(_('출고 완료는 검사·재고 검증 절차로만 처리합니다.'))
        return super().write(vals)

    def unlink(self):
        if self._has_outgoing_evidence():
            raise UserError(_('완료 출고의 재고 이동은 삭제할 수 없습니다.'))
        return super().unlink()


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_outgoing_post_token') is not _OUTGOING_POST_TOKEN:
            defaults = self.default_get(['move_id', 'picking_id'])
            for vals in vals_list:
                effective = dict(defaults, **vals)
                move = self.env['stock.move'].browse(effective.get('move_id'))
                picking = self.env['stock.picking'].browse(effective.get('picking_id')) or move.picking_id
                if picking.picking_type_code == 'outgoing' and picking.state == 'done':
                    raise UserError(_('완료 출고에 재고 상세를 추가할 수 없습니다.'))
        return super().create(vals_list)

    def write(self, vals):
        evidence = {'move_id', 'picking_id', 'product_id', 'product_uom_id', 'quantity', 'lot_id', 'lot_name',
                    'location_id', 'location_dest_id', 'company_id', 'package_id', 'owner_id', 'result_package_id'}
        if evidence.intersection(vals) and self.env.context.get('_outgoing_post_token') is not _OUTGOING_POST_TOKEN:
            target_picking = self.env['stock.picking'].browse(vals.get('picking_id'))
            if target_picking.state == 'done' and target_picking.picking_type_code == 'outgoing':
                raise UserError(_('재고 상세를 완료 출고로 옮길 수 없습니다.'))
            destination = self.env['stock.move'].browse(vals.get('move_id'))
            if (self.move_id | destination)._has_outgoing_evidence():
                raise UserError(_('완료 출고의 LOT·수량 증빙은 수정할 수 없습니다.'))
        return super().write(vals)

    def unlink(self):
        if self.move_id._has_outgoing_evidence():
            raise UserError(_('완료 출고의 LOT·수량 증빙은 삭제할 수 없습니다.'))
        return super().unlink()
