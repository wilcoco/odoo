"""Preserve PO allocation; add a separate notice-backed receiving path."""
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare
from odoo.addons.supplier_portal_purchase.models.supplier_asn import _ASN_WRITE
from .supply_notice import check_base_quantity


class SupplierAsnLine(models.Model):
    _inherit = 'supplier.asn.line'

    no_po_notice_id = fields.Many2one('scm.no.po.notice', string='무발주 수량통보', ondelete='restrict', index=True)

    @api.model_create_multi
    def create(self, vals_list):
        default_notice = self.env.context.get('default_no_po_notice_id')
        notices = self.env['scm.no.po.notice'].browse(sorted({
            v.get('no_po_notice_id') or default_notice
            for v in vals_list if v.get('no_po_notice_id') or default_notice
        }))
        notices._lock()
        records = super().create(vals_list)
        records._check_no_po_scope()
        return records

    def write(self, vals):
        notices = self.no_po_notice_id | self.env['scm.no.po.notice'].browse(vals.get('no_po_notice_id'))
        if notices and set(vals) & {'asn_id', 'product_id', 'qty', 'purchase_line_id', 'no_po_notice_id', 'lot_name'}:
            notices._lock()
            if self.move_ids or self.asn_id.picking_id or any(a.state != 'announced' for a in self.asn_id):
                raise UserError(_('입고에 배정된 무발주 ASN 근거는 변경할 수 없습니다.'))
        result = super().write(vals)
        self._check_no_po_scope()
        return result

    def unlink(self):
        self.no_po_notice_id._lock()
        return super().unlink()

    @api.constrains('no_po_notice_id', 'purchase_line_id', 'asn_id', 'product_id', 'qty')
    def _check_no_po_scope(self):
        for line in self.filtered('no_po_notice_id'):
            notice = line.no_po_notice_id
            if line.purchase_line_id:
                raise ValidationError(_('한 ASN 행에는 구매행 또는 무발주 통보 중 하나만 지정하세요.'))
            if (line.company_id != notice.company_id or line.product_id != notice.product_id
                    or line.asn_id.partner_id.commercial_partner_id != notice.partner_id):
                raise ValidationError(_('ASN과 통보의 회사·공급사·제품이 다릅니다.'))
            check_base_quantity(line.qty, line.product_id)
            if line.asn_id.state != 'cancelled':
                notice._check_issued()
                total = sum(notice.asn_line_ids.filtered(lambda l: l.asn_id.state != 'cancelled').mapped('qty'))
                if float_compare(total, notice.quantity, precision_rounding=notice.uom_id.rounding) > 0:
                    raise ValidationError(_('통보 수량보다 많은 ASN을 배정할 수 없습니다. 취소·잔량을 확인하세요.'))
        for asn in self.asn_id:
            if len(asn.line_ids.no_po_notice_id) > 1:
                raise ValidationError(_('무발주 ASN은 한 요구통보씩 작성하세요. 통보별 취소·잔량 이력을 분리합니다.'))
            if asn.line_ids.no_po_notice_id and any(not l.no_po_notice_id for l in asn.line_ids):
                raise ValidationError(_('무발주 ASN과 구매발주 ASN은 별도 문서로 작성하세요.'))


class SupplierAsn(models.Model):
    _inherit = 'supplier.asn'

    no_po_request_key = fields.Char(readonly=True, copy=False, index=True)
    state = fields.Selection(selection_add=[('closed', '잔량 종료')], ondelete={'closed': 'set default'})
    _sql_constraints = [('no_po_request_key_unique', 'unique(company_id, partner_id, no_po_request_key)',
                         '동일한 협력사 납품 제출번호가 이미 처리되었습니다.')]

    def write(self, vals):
        if 'no_po_request_key' in vals:
            raise UserError(_('협력사 제출번호는 변경할 수 없습니다.'))
        if set(vals) & {'company_id', 'partner_id', 'line_ids'}:
            self.line_ids.no_po_notice_id._lock()
        result = super().write(vals)
        if set(vals) & {'company_id', 'partner_id', 'line_ids'}:
            self.line_ids._check_no_po_scope()
        return result

    def action_create_picking(self):
        self.ensure_one()
        if not self.line_ids.no_po_notice_id:
            return super().action_create_picking()
        self.check_access('write')
        notices = self.line_ids.no_po_notice_id
        notices._lock()
        self._lock_allocation()
        if self.state == 'cancelled':
            raise UserError(_('취소 ASN은 입고할 수 없습니다.'))
        self.line_ids._check_scm_scope()
        self.line_ids._check_no_po_scope()
        active = self.line_ids.move_ids.picking_id.filtered(lambda p: p.state not in ('done', 'cancel'))
        if len(active) > 1:
            raise UserError(_('여러 활성 입고가 연결되어 있습니다. 기존 배정을 확인하세요.'))
        if active:
            return self._picking_action(active)
        if self.state == 'received':
            return self._picking_action(self.picking_id)
        types = notices.agreement_id.picking_type_id
        if len(types) != 1:
            raise UserError(_('입고 유형이 다른 요구통보는 ASN을 분리하세요.'))
        picking = self.env['stock.picking']
        for line in self.line_ids:
            completed = sum(m.product_uom._compute_quantity(m.quantity, line.product_id.uom_id)
                for m in line.move_ids if m.state == 'done' and m.location_id.usage == 'supplier'
                and m.location_dest_id.usage == 'internal')
            remaining = line.qty - completed
            if float_compare(remaining, 0, precision_rounding=line.product_id.uom_id.rounding) <= 0:
                continue
            if not picking:
                picking = picking.create({'picking_type_id': types.id, 'partner_id': self.partner_id.id,
                    'company_id': self.company_id.id, 'origin': ', '.join(notices.mapped('name')),
                    'location_id': types.default_location_src_id.id,
                    'location_dest_id': types.default_location_dest_id.id})
            move = self.env['stock.move'].create({'name': line.product_id.display_name,
                'product_id': line.product_id.id, 'product_uom': line.product_id.uom_id.id,
                'product_uom_qty': remaining, 'picking_id': picking.id, 'company_id': self.company_id.id,
                'location_id': picking.location_id.id, 'location_dest_id': picking.location_dest_id.id,
                'supplier_asn_line_id': line.id})
            move._action_confirm(merge=False)
            # No done quantity or LOT is assumed. Warehouse users count real goods
            # and validate through standard receiving/IQC and backorder workflows.
        if not picking:
            raise UserError(_('입고할 ASN 잔량이 없습니다.'))
        self.with_context(_asn_write=_ASN_WRITE).write({'picking_id': picking.id})
        return self._picking_action(picking)

    def action_cancel(self):
        po = self.filtered(lambda a: not a.line_ids.no_po_notice_id)
        no_po = self - po
        if po:
            super(SupplierAsn, po).action_cancel()
        no_po.check_access('write')
        no_po.line_ids.no_po_notice_id._lock()
        for asn in no_po:
            asn._lock_allocation()
            if asn.state == 'received' or asn.line_ids.move_ids.filtered(lambda m: m.state == 'done'):
                raise UserError(_('실입고 ASN은 취소할 수 없습니다. 반품/잔량 정정 검토가 필요합니다.'))
            # A no-PO allocation is the stock demand itself. Cancel it instead of
            # detaching it and leaving an unbacked ordinary receipt as the PO path does.
            asn.line_ids.move_ids.filtered(lambda m: m.state != 'cancel')._action_cancel()
            asn.with_context(_asn_write=_ASN_WRITE).write({'state': 'cancelled'})
        return True


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model_create_multi
    def create(self, vals_list):
        default_line = self.env.context.get('default_supplier_asn_line_id')
        lines = self.env['supplier.asn.line'].browse(sorted({
            v.get('supplier_asn_line_id') or default_line
            for v in vals_list if v.get('supplier_asn_line_id') or default_line
        }))
        lines.no_po_notice_id._lock()
        records = super().create(vals_list)
        records._check_no_po_receipt()
        return records

    def write(self, vals):
        notices = self.supplier_asn_line_id.no_po_notice_id
        if notices and set(vals) & {'product_uom_qty', 'product_uom', 'quantity', 'state', 'location_id', 'location_dest_id', 'picking_id'}:
            notices._lock()
        result = super().write(vals)
        if notices:
            self._check_no_po_receipt()
        return result

    @api.constrains('supplier_asn_line_id', 'product_id', 'company_id', 'purchase_line_id', 'picking_id', 'product_uom', 'location_id', 'location_dest_id')
    def _check_no_po_receipt(self):
        for move in self.filtered(lambda m: m.supplier_asn_line_id.no_po_notice_id):
            line = move.supplier_asn_line_id
            notice = line.no_po_notice_id
            if move.purchase_line_id:
                raise ValidationError(_('무발주 통보 입고에 구매행을 연결할 수 없습니다.'))
            if (move.company_id != notice.company_id or move.product_id != notice.product_id
                    or move.product_uom.category_id != notice.uom_id.category_id):
                raise ValidationError(_('입고와 통보의 회사·품목·단위가 다릅니다.'))
            if move.location_id.usage == 'supplier' and move.location_dest_id.usage == 'internal':
                if (not move.picking_id or move.picking_id.partner_id.commercial_partner_id != notice.partner_id
                        or move.picking_type_id != notice.agreement_id.picking_type_id):
                    raise ValidationError(_('무발주 입고의 공급사 또는 입고 유형이 통보와 다릅니다.'))
                if move.state != 'cancel':
                    notice._check_issued()
                    if line.asn_id.state == 'cancelled':
                        raise ValidationError(_('취소 ASN의 입고를 생성하거나 복구할 수 없습니다.'))

    def _action_done(self, cancel_backorder=False):
        incoming = self.filtered(lambda m: m.supplier_asn_line_id.no_po_notice_id
            and m.location_id.usage == 'supplier' and m.location_dest_id.usage == 'internal')
        incoming.supplier_asn_line_id.no_po_notice_id._lock()
        incoming._check_no_po_receipt()
        for line in incoming.supplier_asn_line_id:
            line.no_po_notice_id._check_issued()
            completed = sum(m.product_uom._compute_quantity(m.quantity, line.product_id.uom_id)
                for m in line.move_ids if m.state == 'done' and m.location_id.usage == 'supplier'
                and m.location_dest_id.usage == 'internal')
            current = sum(m.product_uom._compute_quantity(m.quantity, line.product_id.uom_id)
                for m in incoming.filtered(lambda m: m.supplier_asn_line_id == line and m.state not in ('done', 'cancel')))
            if float_compare(completed + current, line.qty, precision_rounding=line.product_id.uom_id.rounding) > 0:
                raise UserError(_('실입고 수량이 ASN 수량을 초과합니다. 초과 납품은 별도 통보/ASN 근거가 필요합니다.'))
        result = super()._action_done(cancel_backorder=cancel_backorder)
        # Also cover ORM callers that complete moves rather than clicking the picking.
        incoming.supplier_asn_line_id.asn_id._mark_received_from_picking(incoming.picking_id)
        return result
