from odoo import fields, models


class PurchaseOrder(models.Model):
    """사출 생산계획의 원재료 부족분 자동 발주와 연결."""

    _inherit = "purchase.order"

    injection_planning_run_id = fields.Many2one(
        "injection.planning.run",
        string="연결된 사출계획",
        readonly=True,
        index=True,
        help="사출 생산계획의 원재료 부족분 발주로 생성된 발주서",
    )
