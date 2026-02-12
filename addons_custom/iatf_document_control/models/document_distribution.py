from odoo import api, fields, models


class IatfDocumentDistribution(models.Model):
    _name = "iatf.document.distribution"
    _description = "Document Distribution Record"
    _order = "document_id, distributed_date desc"

    document_id = fields.Many2one(
        "iatf.document", string="Document", required=True, ondelete="cascade", index=True,
    )
    user_id = fields.Many2one("res.users", string="Distributed To", required=True)
    department_id = fields.Many2one("hr.department", string="Department")
    distributed_date = fields.Date(string="Distribution Date", default=fields.Date.today)
    copy_type = fields.Selection(
        [
            ("controlled", "Controlled Copy"),
            ("uncontrolled", "Uncontrolled Copy"),
            ("electronic", "Electronic Access"),
        ],
        string="Copy Type", default="electronic", required=True,
    )
    acknowledged = fields.Boolean(string="Acknowledged", default=False)
    acknowledged_date = fields.Date(string="Acknowledged Date")

    def action_acknowledge(self):
        self.write({
            "acknowledged": True,
            "acknowledged_date": fields.Date.today(),
        })
