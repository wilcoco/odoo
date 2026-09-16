from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare
import logging

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    oqc_inspection_ids = fields.One2many(
        "iatf.process.inspection", "picking_id", string="출하검사",
    )
    oqc_count = fields.Integer(compute="_compute_oqc_count")

    def _compute_oqc_count(self):
        for rec in self:
            rec.oqc_count = len(rec.oqc_inspection_ids)

    def button_validate(self):
        self.check_access("write")
        # 출하 시 OQC 자동 생성
        created = False
        for picking in self:
            if picking.picking_type_code == 'outgoing' and picking._is_scoped_supplier_return():
                continue
            if picking.picking_type_code == "outgoing" and picking.state not in ("done", "cancel") and not picking.sudo().oqc_inspection_ids.filtered(lambda r: r.state != "cancelled"):
                picking.sudo()._create_oqc_inspections()
                created = True
        if created:
            # Raising here would roll back the new inspections on every retry.
            return {
                "type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("출하검사 대기"), "message": _("출하검사를 생성했습니다. 품질 담당자의 판정과 승인 후 다시 출하해 주세요."), "type": "warning", "sticky": True},
            }
        self._check_oqc_release()
        return super().button_validate()

    def _check_oqc_release(self):
        """Validate again at stock completion, including wizard/internal routes."""
        for picking in self.filtered(lambda p: p.picking_type_code == "outgoing" and p.state not in ("done", "cancel")):
            if picking._is_scoped_supplier_return():
                continue
            lots = picking.move_ids.filtered(lambda m: m.state != 'cancel').move_line_ids.filtered(
                lambda line: line.quantity > 0).lot_id.sudo()
            if 'quality_hold' in lots._fields:
                lots._check_quality_usable()
                lots.invalidate_recordset(['quality_hold'])
                if lots.filtered('quality_hold'):
                    raise UserError(_('품질 보류 중인 LOT이 있어 출하할 수 없습니다. 보류 해제 절차를 먼저 완료해 주세요.'))
            inspections = picking.sudo().oqc_inspection_ids.filtered(lambda r: r.state != "cancelled")
            if not inspections:
                raise UserError(_("출하검사(OQC)가 없어 출하할 수 없습니다."))
            products = picking.move_ids.filtered(lambda m: m.state != "cancel" and m.product_id.type != "service").product_id
            if products - inspections.product_id:
                raise UserError(_("출하 품목에 대한 출하검사(OQC)가 누락되었습니다."))
            invalid = inspections.filtered(lambda r: (
                r.inspection_stage != "oqc" or r.company_id != picking.company_id
                or r.state not in ("decided", "closed")
                or r.result not in ("pass", "conditional")
                or r.disposition not in ("ship", "concession")
            ))
            if invalid:
                raise UserError(_("출하검사(OQC)의 합격 판정과 출하 처분을 확인해 주세요: %s") % ", ".join(invalid.mapped("name")))
            inspections._approval_check_approved(_("출하"))

    def _is_scoped_supplier_return(self):
        """A return to the original supplier is not a customer quality release."""
        self.ensure_one()
        moves = self.move_ids.filtered(lambda m: m.state != 'cancel')
        if not moves or any(m.location_dest_id.usage != 'supplier' or not m.origin_returned_move_id for m in moves):
            return False
        origins = moves.origin_returned_move_id.sorted('id')
        origins.check_access('read')
        origins.flush_recordset()
        self.env.cr.execute('SELECT id FROM stock_move WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(origins.ids)])
        self.env.cr.execute('UPDATE stock_move SET write_date=write_date WHERE id IN %s', [tuple(origins.ids)])
        origins.invalidate_recordset()
        for origin in origins:
            returns = moves.filtered(lambda m: m.origin_returned_move_id == origin)
            if origin.state != 'done' or origin.picking_type_id.code != 'incoming' or any(
                    m.company_id != origin.company_id or m.product_id != origin.product_id
                    or m.location_dest_id != origin.location_id
                    or m.picking_id.partner_id.commercial_partner_id != origin.picking_id.partner_id.commercial_partner_id
                    for m in returns):
                raise UserError(_('공급사 반품의 원 입고·회사·품목·거래처·위치가 일치하지 않습니다.'))
            received = {}
            for line in origin.move_line_ids:
                key = line.lot_id.id
                received[key] = received.get(key, 0) + line.product_uom_id._compute_quantity(line.quantity, origin.product_id.uom_id, round=False)
            previous = self.env['stock.move'].sudo().search([
                ('origin_returned_move_id', '=', origin.id), ('state', '=', 'done'), ('id', 'not in', returns.ids)])
            quantities = {}
            for line in (previous | returns).move_line_ids.filtered(lambda l: l.quantity > 0):
                key = line.lot_id.id
                quantities[key] = quantities.get(key, 0) + line.product_uom_id._compute_quantity(line.quantity, origin.product_id.uom_id, round=False)
            if not quantities or any(float_compare(qty, received.get(key, 0), precision_rounding=origin.product_id.uom_id.rounding) > 0 for key, qty in quantities.items()):
                raise UserError(_('원 입고 LOT의 수량을 넘거나 다른 LOT으로 반품할 수 없습니다.'))
        return True

    def _action_done(self):
        self._check_oqc_release()
        return super()._action_done()

    def _create_oqc_inspections(self):
        """출하 확정 시 제품별 출하검사(OQC) 레코드 자동 생성"""
        PQC = self.env["iatf.process.inspection"]
        for move in self.move_ids.filtered(lambda m: m.state not in ("done", "cancel") and m.product_id.type != "service"):
            vals = {
                "company_id": self.company_id.id,
                "inspection_stage": "oqc",
                "picking_id": self.id,
                "product_id": move.product_id.id,
                "lot_id": move.lot_ids[:1].id if move.lot_ids else False,
                "quantity_produced": move.product_uom_qty,
                "quantity_inspected": move.product_uom_qty,
            }
            oqc = PQC.create(vals)
            _logger.info("OQC auto-created: %s for outgoing picking %s, product %s",
                         oqc.name, self.name, move.product_id.name)

    def action_view_oqc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.process.inspection",
            "view_mode": "list,form",
            "domain": [("picking_id", "=", self.id)],
            "name": _("출하검사"),
            "context": {"default_picking_id": self.id, "default_inspection_stage": "oqc"},
        }


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        self.filtered(lambda m: m.state not in ("done", "cancel")).picking_id._check_oqc_release()
        return super()._action_done(cancel_backorder=cancel_backorder)
