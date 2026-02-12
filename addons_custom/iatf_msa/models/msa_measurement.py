from odoo import fields, models


class IatfMsaMeasurement(models.Model):
    _name = "iatf.msa.measurement"
    _description = "MSA Measurement Data Point"
    _order = "operator_id, part_number, trial_number"

    study_id = fields.Many2one(
        "iatf.msa.study", string="MSA Study", required=True, ondelete="cascade", index=True,
    )
    operator_id = fields.Many2one("res.users", string="Operator", required=True)
    part_number = fields.Char(string="Part #", required=True)
    trial_number = fields.Integer(string="Trial #", required=True, default=1)
    measured_value = fields.Float(string="Measured Value", digits=(16, 6), required=True)
    reference_value = fields.Float(string="Reference Value", digits=(16, 6),
                                    help="Known reference value for bias/linearity studies")
    notes = fields.Char(string="Notes")
