from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockLot(models.Model):
    _inherit = "stock.lot"

    quality_hold = fields.Boolean(string="품질 보류", default=False, tracking=True)
    hold_reason = fields.Char(string="보류 사유")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    iqc_inspection_ids = fields.One2many(
        "iatf.incoming.inspection", "picking_id", string="수입검사",
    )
    iqc_count = fields.Integer(compute="_compute_iqc_count")

    def _compute_iqc_count(self):
        for rec in self:
            rec.iqc_count = len(rec.iqc_inspection_ids)

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.picking_type_code == "incoming" and picking.state == "done":
                picking._create_iqc_inspections()
        return res

    def _create_iqc_inspections(self):
        """One draft per actual receipt detail; the stock transaction owns scope."""
        from .iqc_service import service
        self.check_access('write')
        IQC = service(self.env['iatf.incoming.inspection'].sudo())
        for picking in self:
            if not self.env.su and picking.company_id not in self.env.companies:
                raise UserError(_('허용된 회사의 입고만 검사 대상으로 만들 수 있습니다.'))
            for line in picking.move_ids.move_line_ids.filtered(lambda l: l.state == 'done' and l.iqc_receipt_managed and l.quantity > 0):
                self.env.cr.execute('UPDATE stock_move_line SET write_date=write_date WHERE id=%s', [line.id])
                if IQC.search_count([('receipt_move_line_id', '=', line.id)], limit=1):
                    continue
                po_line = line.move_id.purchase_line_id
                IQC.create({
                    'receipt_move_line_id': line.id,
                    'receipt_snapshot': IQC._iqc_receipt_values(line),
                    'picking_id': picking.id, 'company_id': line.company_id.id,
                    'purchase_id': po_line.order_id.id if po_line else False,
                    'supplier_id': picking.partner_id.id, 'product_id': line.product_id.id,
                    'product_uom_id': line.product_uom_id.id,
                    'lot_id': line.lot_id.id, 'quantity_received': line.quantity,
                    'quantity_inspected': 0, 'inspector_id': False,
                    'inspection_type': 'sampling', 'state': 'draft',
                })

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

    def _is_held_output_into_stock(self):
        """**제조 산출물이 보류 재고로 들어오는** 이동인가.

        [아스트라 20260911-15] 이 격리 후보에 한해 배정된 수정이다.
        기존 조건은 `raw_material_production_id or production_id` 였는데
        `production_id` 는 **완제품 move 필드**다(이 파일 주석에도 그렇게 적혀 있다).
        그래서 보류 LOT 의 **완제품 입고 move 자체가 막혔고**, 불량 실물이 재고에
        잡힐 방법이 없었다 — 「추적 가능한 격리 재고에 남긴다」가 성립하지 않았다.

        **`production_id` 가 있다는 이유만으로 면제하지 않는다.** 아래를 전부 확인한다.
          - 실제 제조오더가 있고, 그 오더의 **완제품**(또는 승인된 부산물)이다
          - 회사가 같다
          - **출발이 생산 위치**(`usage == 'production'`)이고
          - **도착이 같은 회사 내부 재고**다 (고객·공급자 등 외부 직송은 제외)
          - 수량이 **양수**다 (역방향·음수 이동 제외)
          - 원재료 소비 이동이 아니다
        """
        self.ensure_one()
        mo = self.production_id
        if not mo or self.raw_material_production_id:
            return False
        if self.company_id and mo.company_id and self.company_id != mo.company_id:
            return False
        finished = mo.move_finished_ids
        if self not in finished:
            return False
        if self.location_id.usage != 'production':
            return False
        if self.location_dest_id.usage != 'internal':
            return False
        if self.location_dest_id.company_id and self.company_id \
                and self.location_dest_id.company_id != self.company_id:
            return False
        quantity = self.quantity if 'quantity' in self._fields else self.product_uom_qty
        if not quantity or quantity <= 0:
            return False
        return True

    def _kr_check_held_lots(self, stage):
        """보류 로트의 **유출**을 막는다. 제조 산출물의 **유입**은 막지 않는다.

        원재료 소비와 보류 완제품의 고객출하·다른 생산 투입은 그대로 막힌다."""
        for move in self:
            if not (move.raw_material_production_id or move.production_id):
                continue
            if move._is_held_output_into_stock():
                # 실물은 이미 만들어졌다. 보류 재고로 **들어오는** 것까지 막으면
                # 어디에도 기록되지 않는다. 쓰는 것은 하류에서 막는다.
                continue
            lots = move.lot_ids | move.move_line_ids.lot_id
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
        return super()._action_done(cancel_backorder=cancel_backorder)
