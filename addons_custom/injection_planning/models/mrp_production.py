from odoo import fields, models


class MrpProductionPlanning(models.Model):
    _inherit = "mrp.production"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="생산계획", index=True,
    )
