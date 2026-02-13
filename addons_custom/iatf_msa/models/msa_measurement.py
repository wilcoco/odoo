from odoo import fields, models


class IatfMsaMeasurement(models.Model):
    _name = "iatf.msa.measurement"
    _description = "MSA Measurement Data Point"
    _order = "operator_id, part_number, trial_number"

    study_id = fields.Many2one(
        "iatf.msa.study", string="MSA 연구", required=True, ondelete="cascade", index=True,
    )
    operator_id = fields.Many2one("res.users", string="측정자", required=True)
    part_number = fields.Char(string="부품 #", required=True)
    trial_number = fields.Integer(string="반복 #", required=True, default=1)
    measured_value = fields.Float(string="측정값", digits=(16, 6), required=True)
    reference_value = fields.Float(string="기준값", digits=(16, 6),
                                    help="Known reference value for bias/linearity studies")
    notes = fields.Char(string="비고")
