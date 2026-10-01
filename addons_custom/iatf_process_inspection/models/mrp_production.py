from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

from .process_inspection import _AUTO_EVIDENCE_TOKEN

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
        # MO 완료 권한 검증 이후의 자동 실적 생성 훅. 현장 담당자에게
        # 공정검사 마스터/승인 권한을 부여하지 않아도 생산 완료는 가능해야 한다.
        # 활성 회사가 아니라 **이 MO 의 회사**로 만든다. `with_company` 를 걸지 않으면
        # 회사 1 에서 회사 5 의 MO 를 완료할 때 검사 기록이 회사 1 로 생긴다.
        # (제3자 재검토 R08 — 앞선 수정이 단위 MO 경로만 덮었다)
        PQC = self.env["iatf.process.inspection"].sudo().with_company(self.company_id)
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
            # [아스트라 20260912 05:27] 「집계 search→누적 write 구간에는 묶음
            # 생성·동시 누적을 **직렬화하는 명시적 잠금이 보이지 않습니다.**
            # 서로 다른 두 단위의 동시 완료 시 묶음 중복 생성/수량 또는 기여 ID
            # 유실을 방지하십시오.」
            #
            # 맞습니다. 두 단위가 동시에 완료되면 둘 다 `search` 에서 빈 결과를
            # 보고 묶음을 **두 개** 만들거나, 서로의 누적을 덮어씁니다.
            # 반복읽기에서는 `SELECT … FOR UPDATE` 로도 부족하고 **대상 행을 실제로
            # UPDATE** 해야 뒤에 온 트랜잭션이 직렬화 실패로 되돌아갑니다.
            # 묶음의 기준은 계획 MO 이므로 그 행을 잠급니다.
            target.flush_recordset()
            self.env.cr.execute(
                "UPDATE mrp_production SET write_date = write_date WHERE id = %s",
                [target.id])
            target.invalidate_recordset()
            PQC = PQC.with_context(_process_auto_evidence_token=_AUTO_EVIDENCE_TOKEN)
            runs = PQC.search([
                ("production_id", "=", target.id),
                ("production_date", "=", prod_date),
                ("shift", "=", shift or False),
                ("company_id", "=", self.company_id.id),
                ("product_id", "=", self.product_id.id),
                ("inspection_stage", "=", "ipqc"),
                ("correction_of_id", "=", False),
            ], order="id")
            # 입력/판정과 누적이 같은 검사 행 잠금을 사용한다. 이미 다른 묶음에
            # 기여한 단위는 재호출 때 새로운 검사서에 다시 세지 않는다.
            runs._lock_auto_evidence_records(runs)
            if any(self.id in (run.run_unit_mo_ids or []) for run in runs):
                return
            existing = runs.filtered(lambda run: run._run_can_accumulate())[:1]
            if existing:
                # [아스트라 20260912 05:1x] 「기존 묶음 메서드가 `quantity_inspected`
                # 를 `qty_produced` 만큼 자동 누적하고 있습니다. **생산량을 검사량으로
                # 자동 간주할 수 없습니다.** … **반복 완료는 생산량/검사량을 중복
                # 누적하지 않아야** 하고, 이미 승인된 검사서에 후속 실적을 덧붙여
                # **승인 범위를 조용히 늘리면 안 됩니다.**」
                #
                # 셋 다 맞습니다. 검사량은 **사람이 실제로 검사한 수**이고,
                # 같은 단위 MO 를 다시 완료해도 생산량은 한 번만 세며,
                # 승인된 검사서는 **건드리지 않고 그 사실을 남깁니다.**
                contributed = list(existing.run_unit_mo_ids or [])
                self._assert_run_unit_contribution(target, prod_date, shift)
                existing.with_context(
                    _process_auto_evidence_token=_AUTO_EVIDENCE_TOKEN).write({
                        "quantity_produced": existing.quantity_produced + self.qty_produced,
                        # **검사량은 올리지 않는다.** 만든 것과 검사한 것은 다르다.
                        "run_unit_mo_ids": contributed + [self.id],
                    })
                return
            self._assert_run_unit_contribution(target, prod_date, shift)
            pqc = PQC.create({
                "company_id": self.company_id.id,  # 활성 회사가 아니라 MO 의 회사 (제3자 검토 H13)
                "inspection_stage": "ipqc",
                "article_stage": "first",
                "production_id": target.id,
                "product_id": self.product_id.id,
                "production_date": prod_date,
                "shift": shift or False,
                "lot_id": self.lot_producing_id.id if self.lot_producing_id else False,
                "workcenter_id": self.workcenter_id.id if "workcenter_id" in self._fields and self.workcenter_id else False,
                "quantity_produced": self.qty_produced,
                # **검사 전이다.** 검사량은 실제로 검사한 뒤에 기록한다
                # (0 이면 `action_decide` 가 판정을 막는다 — 그것이 맞다).
                "quantity_inspected": 0.0,
                "run_unit_mo_ids": [self.id],
            })
            _logger.info("PQC(초물) run aggregate created: %s for %s %s %s",
                         pqc.name, target.name, prod_date, shift)
            return
        vals = {
            "company_id": self.company_id.id,   # 일반 MO 경로에도 명시 (R08)
            "inspection_stage": "final",
            "production_id": self.id,
            "product_id": self.product_id.id,
            "lot_id": self.lot_producing_id.id if self.lot_producing_id else False,
            "workcenter_id": self.workcenter_id.id if hasattr(self, "workcenter_id") and self.workcenter_id else False,
            "quantity_produced": self.qty_produced,
            # 일반 MO 도 마찬가지다 — 만든 수를 검사한 수로 간주하지 않는다.
            "quantity_inspected": 0.0,
        }
        pqc = PQC.create(vals)
        _logger.info("PQC auto-created: %s for MO %s, product %s",
                     pqc.name, self.name, self.product_id.name)

    def _assert_run_unit_contribution(self, target, prod_date, shift):
        """이 단위 실적을 런 묶음에 **셀 수 있는가**.

        [아스트라 20260912 05:27] 「**parent/회사/완료 여부/수량/날짜·교대 및 기여
        단위 LOT 근거를 검증해야 합니다.**」

        묶음은 서버만 쓸 수 있지만, 서버가 **아무것이나** 세도 된다는 뜻은 아니다.
        """
        self.ensure_one()
        if not self.is_ip_unit_mo:
            raise UserError(_('사출 단위 실적만 런 묶음에 셀 수 있습니다.'))
        if target != self and self.parent_planning_mo_id != target:
            raise UserError(_('이 단위 실적의 계획 MO 가 묶음 대상과 다릅니다.'))
        if target.company_id != self.company_id:
            raise UserError(_('계획 MO 와 단위 실적의 회사가 다릅니다.'))
        if target.product_id != self.product_id:
            raise UserError(_('계획 MO 와 단위 실적의 품목이 다릅니다.'))
        if self.state != 'done':
            raise UserError(_('완료되지 않은 단위 실적은 런 묶음에 세지 않습니다.'))
        if not self.qty_produced or self.qty_produced <= 0:
            raise UserError(_('실적 수량이 없는 단위는 런 묶음에 세지 않습니다.'))
        if self.product_id.tracking != 'none' and not self.lot_producing_id:
            raise UserError(_('추적 품목의 단위 실적에는 생산 LOT 근거가 필요합니다.'))
        return True

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
