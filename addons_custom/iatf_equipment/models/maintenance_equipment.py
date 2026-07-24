from odoo import api, fields, models, _


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    # ── IATF 설비 브릿지 (B3) ──
    iatf_equipment_id = fields.Many2one("iatf.equipment", string="IATF 설비", tracking=True)
    iatf_pm_count = fields.Integer(compute="_compute_iatf_counts", string="PM 건수")
    iatf_breakdown_count = fields.Integer(compute="_compute_iatf_counts", string="고장 건수")

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
