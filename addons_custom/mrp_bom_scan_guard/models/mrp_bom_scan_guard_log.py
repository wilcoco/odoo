# addons_custom/mrp_bom_scan_guard/models/mrp_bom_scan_guard_log.py
from odoo import api, fields, models, _


class MrpBomScanGuardLog(models.Model):
    _name = "mrp.bom.scan.guard.log"
    _description = "BOM Scan Guard Logs"
    _order = "id desc"

    workorder_id = fields.Many2one("mrp.workorder", string="Work Order", required=True, index=True)
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order", related="workorder_id.production_id", store=True, readonly=True
    )
    operation_id = fields.Many2one(
        "mrp.routing.workcenter", string="Operation", related="workorder_id.operation_id", store=True, readonly=True
    )

    scan_value = fields.Char(string="Scanned Value", required=True)
    matched_product_id = fields.Many2one("product.product", string="Matched Product")

    result_state = fields.Selection(
        [
            ("ok", "OK"),
            ("wrong_operation", "Wrong Operation"),
            ("not_in_bom", "Not in BOM"),
            ("over_consumed", "Over-consumed"),
            ("not_found", "Not Found"),
        ],
        string="Result",
        required=True,
        index=True,
    )
    message = fields.Html(string="Message", sanitize=False)

    mismatch = fields.Boolean(string="Is Mismatch", compute="_compute_mismatch", store=True)

    user_id = fields.Many2one("res.users", string="User", default=lambda self: self.env.user, readonly=True)
    company_id = fields.Many2one(
        "res.company", string="Company", related="workorder_id.company_id", store=True, readonly=True
    )

    @api.depends("result_state")
    def _compute_mismatch(self):
        for rec in self:
            rec.mismatch = rec.result_state in ("wrong_operation", "not_in_bom", "not_found")
