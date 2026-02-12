from odoo import fields, models


class IatfSpcSubgroup(models.Model):
    _name = "iatf.spc.subgroup"
    _description = "SPC Subgroup Data"
    _order = "sequence, id"

    study_id = fields.Many2one(
        "iatf.spc.study", string="SPC Study", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(string="Subgroup #", default=10)
    sample_date = fields.Datetime(string="Sample Date", default=fields.Datetime.now)
    operator_id = fields.Many2one("res.users", string="Operator", default=lambda self: self.env.user)

    # Up to 10 individual measurements per subgroup
    x1 = fields.Float(string="X1", digits=(16, 4))
    x2 = fields.Float(string="X2", digits=(16, 4))
    x3 = fields.Float(string="X3", digits=(16, 4))
    x4 = fields.Float(string="X4", digits=(16, 4))
    x5 = fields.Float(string="X5", digits=(16, 4))
    x6 = fields.Float(string="X6", digits=(16, 4))
    x7 = fields.Float(string="X7", digits=(16, 4))
    x8 = fields.Float(string="X8", digits=(16, 4))
    x9 = fields.Float(string="X9", digits=(16, 4))
    x10 = fields.Float(string="X10", digits=(16, 4))

    # Computed
    sg_mean = fields.Float(string="X̄", digits=(16, 4), compute="_compute_stats", store=True)
    sg_range = fields.Float(string="R", digits=(16, 4), compute="_compute_stats", store=True)
    is_ooc = fields.Boolean(string="Out of Control", default=False)

    notes = fields.Char(string="Notes")

    def _get_values(self):
        self.ensure_one()
        n = self.study_id.subgroup_size or 5
        all_fields = [self.x1, self.x2, self.x3, self.x4, self.x5,
                       self.x6, self.x7, self.x8, self.x9, self.x10]
        return [v for v in all_fields[:n] if v != 0.0 or True][:n]

    def _compute_stats(self):
        for sg in self:
            vals = sg._get_values()
            if vals:
                sg.sg_mean = sum(vals) / len(vals)
                sg.sg_range = max(vals) - min(vals)
            else:
                sg.sg_mean = 0.0
                sg.sg_range = 0.0
