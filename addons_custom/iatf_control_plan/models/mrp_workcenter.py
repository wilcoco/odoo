from odoo import api, fields, models, _


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    # ── IATF 연동 (B5) ──
    control_plan_ids = fields.One2many(
        "iatf.control.plan", compute="_compute_control_plans",
        string="관리계획서",
    )
    control_plan_count = fields.Integer(compute="_compute_control_plans")
    iatf_equipment_ids = fields.One2many(
        "iatf.equipment", "workcenter_id", string="IATF 설비",
    )
    iatf_equipment_count = fields.Integer(compute="_compute_equipment_count")

    def _compute_control_plans(self):
        CP = self.env.get("iatf.control.plan")
        for wc in self:
            if CP:
                # CP 라인에서 이 작업장의 설비를 참조하는 CP 찾기
                cps = CP.search([
                    ("line_ids.machine_device", "ilike", wc.name),
                    ("state", "=", "approved"),
                ])
                wc.control_plan_ids = cps
                wc.control_plan_count = len(cps)
            else:
                wc.control_plan_ids = False
                wc.control_plan_count = 0

    def _compute_equipment_count(self):
        for wc in self:
            wc.iatf_equipment_count = len(wc.iatf_equipment_ids)

    def action_view_control_plans(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.control.plan",
            "view_mode": "list,form",
            "domain": [("id", "in", self.control_plan_ids.ids)],
            "name": _("관리계획서: %s") % self.name,
        }

    def action_view_iatf_equipment(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.equipment",
            "view_mode": "list,form",
            "domain": [("workcenter_id", "=", self.id)],
            "name": _("IATF 설비: %s") % self.name,
        }
