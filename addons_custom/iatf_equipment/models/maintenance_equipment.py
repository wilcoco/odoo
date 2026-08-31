from odoo import api, fields, models, _


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    # ── IATF 설비 브릿지 (B3) ──
    iatf_equipment_id = fields.Many2one("iatf.equipment", string="IATF 설비", tracking=True)
    iatf_pm_count = fields.Integer(compute="_compute_iatf_counts", string="PM 건수")
    iatf_breakdown_count = fields.Integer(compute="_compute_iatf_counts", string="고장 건수")

    # ── 신뢰성 지표 단일화 ──
    # 표준 maintenance.mixin 의 mtbf/mttr 은 '일' 단위이고 effective_date 부터의 달력 경과일로
    # 계산한다. 설비를 돌리지 않은 시간까지 포함하므로 TPM 지표가 아니며, 같은 이름의 값이
    # IATF 설비대장(가동시간 기준, '시간' 단위)과 두 벌 존재하면 화면마다 숫자가 달라진다.
    # → IATF 설비가 연결된 경우 표준 통계 그룹을 감추고 아래 related 값만 노출한다.
    iatf_mtbf = fields.Float(related="iatf_equipment_id.mtbf", string="MTBF (시간)", readonly=True)
    iatf_mttr = fields.Float(related="iatf_equipment_id.mttr", string="MTTR (시간)", readonly=True)
    iatf_availability_rate = fields.Float(
        related="iatf_equipment_id.availability_rate", string="가동률 (%)", readonly=True)
    iatf_runtime_hours = fields.Float(
        related="iatf_equipment_id.runtime_hours", string="적용 가동시간", readonly=True)
    iatf_runtime_source = fields.Selection(
        related="iatf_equipment_id.runtime_source", string="가동시간 출처", readonly=True)

    def _compute_iatf_counts(self):
        PM = self.env.get("iatf.pm.schedule")
        BD = self.env.get("iatf.equipment.breakdown")
        for rec in self:
            eq = rec.iatf_equipment_id
            if eq and PM:
                rec.iatf_pm_count = PM.search_count([("equipment_id", "=", eq.id)])
            else:
                rec.iatf_pm_count = 0
            if eq and BD:
                rec.iatf_breakdown_count = BD.search_count([("equipment_id", "=", eq.id)])
            else:
                rec.iatf_breakdown_count = 0

    def action_view_iatf_equipment(self):
        self.ensure_one()
        if self.iatf_equipment_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "iatf.equipment",
                "res_id": self.iatf_equipment_id.id,
                "view_mode": "form",
                "target": "current",
            }

    def action_view_iatf_pm(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.pm.schedule",
            "view_mode": "list,form",
            "domain": [("equipment_id", "=", self.iatf_equipment_id.id)] if self.iatf_equipment_id else [("id", "=", 0)],
            "name": _("예방보전 이력"),
        }

    def action_view_iatf_breakdown(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.equipment.breakdown",
            "view_mode": "list,form",
            "domain": [("equipment_id", "=", self.iatf_equipment_id.id)] if self.iatf_equipment_id else [("id", "=", 0)],
            "name": _("고장 이력"),
        }


class IatfEquipment(models.Model):
    _inherit = "iatf.equipment"

    maintenance_equipment_id = fields.Many2one("maintenance.equipment", string="Odoo 보전 설비")
