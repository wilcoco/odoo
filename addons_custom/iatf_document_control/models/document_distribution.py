from odoo import api, fields, models


class IatfDocumentDistribution(models.Model):
    _name = "iatf.document.distribution"
    _description = "Document Distribution Record"
    _order = "document_id, distributed_date desc"

    document_id = fields.Many2one(
        "iatf.document", string="문서", required=True, ondelete="cascade", index=True,
    )
    user_id = fields.Many2one("res.users", string="배포 대상", required=True)
    department_id = fields.Many2one("hr.department", string="부서")
    distributed_date = fields.Date(string="배포일", default=fields.Date.today)
    copy_type = fields.Selection(
        [
            ("controlled", "관리본"),
            ("uncontrolled", "비관리본"),
            ("electronic", "전자 접근"),
        ],
        string="복사 유형", default="electronic", required=True,
    )
    acknowledged = fields.Boolean(string="확인", default=False)
    acknowledged_date = fields.Date(string="확인일")

    def action_acknowledge(self):
        self.write({
            "acknowledged": True,
            "acknowledged_date": fields.Date.today(),
        })
