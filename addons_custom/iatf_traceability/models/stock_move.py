from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, cancel_backorder=False):
        res = super()._action_done(cancel_backorder=cancel_backorder)
        for move in res.filtered(lambda m: m.state == "done" and m.lot_ids):
            move._create_traceability_record()
        return res

    def _create_traceability_record(self):
        """로트가 있는 재고 이동 완료 시 추적 기록 자동 생성.

        sudo 사용: 시스템 자동 기록이므로, 이동을 완료한 사용자(현장·입고 담당)가
        IATF 추적성 그룹이 없어도 접근 에러 없이 기록돼야 한다. 수동 열람/편집
        권한은 ACL(읽기=내부 사용자, 쓰기=추적성 그룹)이 계속 통제한다."""
        TraceRecord = self.env["iatf.traceability.record"].sudo()
        for lot in self.lot_ids:
            vals = {
                "product_id": self.product_id.id,
                "lot_id": lot.id,
                "quantity": self.quantity,
                "process_step": _("%s → %s") % (
                    self.location_id.complete_name or self.location_id.name,
                    self.location_dest_id.complete_name or self.location_dest_id.name,
                ),
                "production_id": self.production_id.id if self.production_id else False,
            }
            # 제조오더가 있으면 투입 자재 로트도 기록
            if self.production_id:
                input_lots = self.production_id.move_raw_ids.filtered(
                    lambda m: m.state == "done"
                ).mapped("lot_ids")
                vals["input_lot_ids"] = [(6, 0, input_lots.ids)]

            rec = TraceRecord.create(vals)
            _logger.info("Traceability auto-created: %s for lot %s, move %s",
                         rec.name, lot.name, self.reference or self.name)
