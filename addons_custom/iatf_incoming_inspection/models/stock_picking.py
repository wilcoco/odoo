from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
import logging

_logger = logging.getLogger(__name__)
_IQC_RELEASE = object()
_IQC_HOLD = object()


class StockLot(models.Model):
    _inherit = "stock.lot"

    quality_hold = fields.Boolean(string="품질 보류", default=False, tracking=True)
    hold_reason = fields.Char(string="보류 사유")
    hold_version = fields.Integer(string="보류 버전", default=0, readonly=True, copy=False)
    hold_origin = fields.Selection([('iqc', '입고 검사'), ('manual', '수동/기타 보류')], default='manual', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any(set(vals) & {'hold_version', 'hold_origin'} for vals in vals_list):
            raise AccessError(_('보류 버전은 서버에서 관리합니다.'))
        return super().create([dict(vals, hold_origin='manual', hold_version=1 if vals.get('quality_hold', self.env.context.get('default_quality_hold')) else 0) for vals in vals_list])

    def _lock_quality(self):
        if self:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM stock_lot WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(sorted(self.ids))])
            self.env.cr.execute('UPDATE stock_lot SET write_date=write_date WHERE id IN %s', [tuple(sorted(self.ids))])
            self.invalidate_recordset()

    def _check_quality_usable(self):
        """Shared consumption/shipping gate; serialize with new holds and releases."""
        self._lock_quality()
        held = self.filtered('quality_hold')
        if held:
            raise UserError(_('품질 보류 중인 LOT은 사용할 수 없습니다: %s') % ', '.join(held.mapped('name')))
        released = self.env['iatf.incoming.inspection'].sudo().search([('lot_id', 'in', self.ids), ('released_at', '!=', False), ('state', '!=', 'cancelled')])
        if any(r.decision_snapshot != r._evidence() for r in released):
            raise UserError(_('해제 근거가 변경된 LOT이 있습니다. 수입검사 근거를 다시 확인해 주세요.'))
        return True

    def write(self, vals):
        if set(vals) & {'hold_version', 'hold_origin'}:
            raise AccessError(_('보류 버전은 서버에서 관리합니다.'))
        if set(vals) & {'quality_hold', 'hold_reason', 'product_id', 'company_id'}:
            self.check_access('write')
            self._lock_quality()
        if set(vals) & {'product_id', 'company_id'} and self.env['iatf.incoming.inspection'].sudo().search_count([('lot_id', 'in', self.ids)]):
            raise UserError(_('검사 근거가 있는 LOT의 품목·회사는 변경할 수 없습니다.'))
        if "quality_hold" in vals and not vals["quality_hold"]:
            self.invalidate_recordset(["quality_hold"])
            if self.filtered("quality_hold"):
                permission = self.env.context.get("_iqc_release")
                if not (
                    isinstance(permission, tuple) and len(permission) == 2
                    and permission[0] is _IQC_RELEASE
                    and permission[1] == tuple(self.ids)
                ):
                    raise AccessError(_("품질 보류는 LOT 직접 수정으로 해제할 수 없습니다. 수입검사 판정 절차를 사용해 주세요."))
        for lot in self:
            changes = dict(vals)
            if vals.get('quality_hold') or (lot.quality_hold and 'hold_reason' in vals and not ('quality_hold' in vals and not vals['quality_hold'])):
                changes['hold_version'] = lot.hold_version + 1
                changes['hold_origin'] = 'iqc' if self.env.context.get('_iqc_hold') is _IQC_HOLD and (not lot.quality_hold or lot.hold_origin == 'iqc') else 'manual'
            super(StockLot, lot).write(changes)
        return True

    def _place_iqc_hold(self, reason):
        return self.with_context(_iqc_hold=_IQC_HOLD).write({'quality_hold': True, 'hold_reason': reason})

    def _release_quality_hold_from_iqc(self, inspection):
        """Private, record-bound capability; client context cannot authorize release."""
        self.ensure_one()
        inspection.ensure_one()
        inspection.check_access("write")
        self._lock_quality()
        inspection._check_release_evidence()
        if (
            inspection.lot_id != self or inspection.product_id != self.product_id
            or inspection.company_id != self.company_id
            or inspection.state not in ("decided", "closed")
            or inspection.result not in ("pass", "conditional")
        ):
            raise UserError(_("해제할 LOT과 합격한 수입검사의 품목·회사·판정을 확인해 주세요."))
        return self.with_context(_iqc_release=(_IQC_RELEASE, tuple(self.ids))).write({
            "quality_hold": False, "hold_reason": False,
        })


class StockPicking(models.Model):
    _inherit = "stock.picking"

    iqc_inspection_ids = fields.One2many(
        "iatf.incoming.inspection", "picking_id", string="수입검사",
    )
    iqc_count = fields.Integer(compute="_compute_iqc_count")

    def _compute_iqc_count(self):
        for rec in self:
            rec.iqc_count = len(rec.iqc_inspection_ids)

    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            if picking.picking_type_code == "incoming" and picking.state == "done":
                picking._create_iqc_inspections()
        return res

    def _create_iqc_inspections(self):
        """Completed move/LOT quantities in product UoM, once per receipt scope."""
        from .lifecycle import _LIFECYCLE
        for picking in self:
            if picking.state != 'done' or picking.picking_type_code != 'incoming' or not picking.partner_id:
                continue
            picking.check_access('write')
            self.env.cr.execute('SELECT id FROM stock_picking WHERE id=%s FOR UPDATE', [picking.id])
            self.env.cr.execute('UPDATE stock_picking SET write_date=write_date WHERE id=%s', [picking.id])
            IQC = self.env['iatf.incoming.inspection'].sudo().with_company(picking.company_id).with_context(_iqc_lifecycle=_LIFECYCLE)
            held_lots = set()
            for move in picking.move_ids.filtered(lambda m: m.state == 'done' and m.product_id.type != 'service' and not m.origin_returned_move_id):
                quantities = {}
                for line in move.move_line_ids.filtered(lambda l: l.quantity > 0):
                    lot = line.lot_id
                    quantities[lot] = quantities.get(lot, 0) + line.product_uom_id._compute_quantity(line.quantity, move.product_id.uom_id, round=False)
                for lot, quantity in quantities.items():
                    domain = [('source_move_id', '=', move.id), ('lot_id', '=', lot.id or False)]
                    if IQC.search_count(domain):
                        continue
                    if lot and lot.id not in held_lots:
                        lot.sudo()._place_iqc_hold(_('IQC 검사 대기: %s') % picking.name)
                        held_lots.add(lot.id)
                    IQC.create({'picking_id': picking.id, 'source_move_id': move.id,
                                'company_id': picking.company_id.id,
                                'purchase_id': move.purchase_line_id.order_id.id if 'purchase_line_id' in move._fields else False,
                                'supplier_id': picking.partner_id.id, 'product_id': move.product_id.id,
                                'lot_id': lot.id or False, 'quantity_received': quantity,
                                'quantity_inspected': quantity, 'inspection_type': 'sampling'})

    def _get_purchase_order_id(self):
        """origin 필드에서 PO 찾기"""
        if self.origin:
            po = self.env["purchase.order"].search([("name", "=", self.origin)], limit=1)
            return po.id if po else False
        return False

    def action_view_iqc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.incoming.inspection",
            "view_mode": "list,form",
            "domain": [("picking_id", "=", self.id)],
            "name": _("수입검사"),
            "context": {"default_picking_id": self.id},
        }


class StockMove(models.Model):
    _inherit = "stock.move"

    def _kr_check_held_lots(self, stage):
        """원자재 소비 move 의 보류 로트 차단. raw_material_production_id 가 원자재 move 의
        정확한 링크 (기존 production_id 는 완제품 move 필드 — 투입을 못 거르던 결함 교정)."""
        for move in self:
            if not (move.raw_material_production_id or move.production_id):
                continue
            lots = move.lot_ids | move.move_line_ids.lot_id
            lots.sudo()._check_quality_usable()
            lots.invalidate_recordset(["quality_hold", "hold_reason"])
            held = lots.filtered(lambda l: l.quality_hold)
            if held:
                raise UserError(_(
                    "품질 보류 중인 로트는 제조에 투입할 수 없습니다. (%s)\n"
                    "보류 로트: %s\n사유: %s"
                ) % (
                    stage,
                    ", ".join(held.mapped("name")),
                    ", ".join(filter(None, held.mapped("hold_reason"))),
                ))

    def _action_confirm(self, merge=True, merge_into=False):
        """확정 시점 차단 (L3-1)"""
        self._kr_check_held_lots(_("확정 시"))
        return super()._action_confirm(merge=merge, merge_into=merge_into)

    def _action_done(self, cancel_backorder=False):
        """실소비 시점 차단 — 확정 후 lot 을 지정하는 일반 경로 보강 (L3-1 확장)"""
        self._kr_check_held_lots(_("소비 시"))
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        moves.picking_id.filtered(lambda p: p.picking_type_code == 'incoming' and p.state == 'done')._create_iqc_inspections()
        return moves
