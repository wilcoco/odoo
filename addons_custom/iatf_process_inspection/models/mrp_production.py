from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    pqc_inspection_ids = fields.One2many(
        "iatf.process.inspection", "production_id", string="공정검사",
    )
    pqc_count = fields.Integer(compute="_compute_pqc_count")

    def _compute_pqc_count(self):
        for rec in self:
            rec.pqc_count = len(rec.pqc_inspection_ids)

    def button_mark_done(self):
        res = super().button_mark_done()
        for production in self:
            if production.state == "done":
                production._create_pqc_inspection()
        return res

    def _create_pqc_inspection(self):
        """제조오더 완료 시 검사 레코드 자동 생성.
        단위 실적 MO(PLC 개당)는 개별 생성하지 않고 계획 MO 단위로 묶는다 —
        하루 수천 타의 검사서 폭증 방지. 첫 단위 완료 시 초물 1건, 이후는 수량 누적."""
        PQC = self.env["iatf.process.inspection"]
        if "is_ip_unit_mo" in self._fields and self.is_ip_unit_mo:
            # 묶음 단위 = 계획 MO × 생산일 × 교대 — 회사양식 초/중/종물이 생산 런(일자·교대)
            # 단위로 반복되는 실무와 정합 (계획 MO 전체당 1건은 며칠짜리 생산에 너무 성김).
            plan = self.parent_planning_mo_id if "parent_planning_mo_id" in self._fields else self.browse()
            target = plan or self
            prod_date = fields.Date.context_today(self)
            if self.date_finished:
                prod_date = fields.Date.to_date(str(self.date_finished)[:10])
            shift = ""
            if "inj_shift" in self._fields and self.inj_shift:
                shift = dict(self._fields["inj_shift"]._description_selection(self.env)
                             ).get(self.inj_shift, self.inj_shift)
            existing = PQC.search([
                ("production_id", "=", target.id),
                ("production_date", "=", prod_date),
                ("shift", "=", shift or False),
            ], order="id", limit=1)
            if existing:
                if existing.approval_state not in ("approved",):
                    existing.write({
                        "quantity_produced": existing.quantity_produced + self.qty_produced,
                        "quantity_inspected": existing.quantity_inspected + self.qty_produced,
                    })
                return
            pqc = PQC.create({
                "inspection_stage": "ipqc",
                "article_stage": "first",
                "production_id": target.id,
                "product_id": self.product_id.id,
                "production_date": prod_date,
                "shift": shift or False,
                "lot_id": self.lot_producing_id.id if self.lot_producing_id else False,
                "workcenter_id": self.workcenter_id.id if "workcenter_id" in self._fields and self.workcenter_id else False,
                "quantity_produced": self.qty_produced,
                "quantity_inspected": self.qty_produced,
            })
            _logger.info("PQC(초물) run aggregate created: %s for %s %s %s",
                         pqc.name, target.name, prod_date, shift)
            return
        vals = {
            "inspection_stage": "final",
            "production_id": self.id,
            "product_id": self.product_id.id,
            "lot_id": self.lot_producing_id.id if self.lot_producing_id else False,
            "workcenter_id": self.workcenter_id.id if hasattr(self, "workcenter_id") and self.workcenter_id else False,
            "quantity_produced": self.qty_produced,
            "quantity_inspected": self.qty_produced,
        }
        pqc = PQC.create(vals)
        _logger.info("PQC auto-created: %s for MO %s, product %s",
                     pqc.name, self.name, self.product_id.name)

    def action_view_pqc(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.process.inspection",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "name": _("공정검사"),
            "context": {"default_production_id": self.id},
        }
