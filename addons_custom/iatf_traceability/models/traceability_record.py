from odoo import api, fields, models, _


class IatfTraceabilityRecord(models.Model):
    _name = "iatf.traceability.record"
    _description = "Process Traceability Record (IATF 16949 §8.5.2)"
    _inherit = ["mail.thread"]
    _order = "record_date desc, id desc"

    name = fields.Char(string="Reference", required=True, copy=False, readonly=True,
                        default=lambda self: _("New"))

    # ── What ──
    product_id = fields.Many2one("product.product", string="Product", required=True, index=True, tracking=True)
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial", index=True, tracking=True)

    # ── Where / When ──
    record_date = fields.Datetime(string="Record Date", default=fields.Datetime.now, required=True)
    workcenter_id = fields.Many2one("mrp.workcenter", string="Work Center")
    workorder_id = fields.Many2one("mrp.workorder", string="Work Order")
    production_id = fields.Many2one("mrp.production", string="Manufacturing Order", index=True)

    # ── Process data ──
    process_step = fields.Char(string="Process Step")
    operator_id = fields.Many2one("res.users", string="Operator", default=lambda self: self.env.user)
    quantity = fields.Float(string="Quantity")

    # ── Input materials (component lots used) ──
    input_lot_ids = fields.Many2many(
        "stock.lot", "iatf_trace_input_lot_rel", "record_id", "lot_id",
        string="Input Component Lots",
        help="Lots/serials of raw materials consumed in this step.",
    )

    # ── Measurements / Parameters ──
    parameter_ids = fields.One2many(
        "iatf.traceability.parameter", "record_id", string="Process Parameters",
    )

    # ── Quality ──
    inspection_result = fields.Selection(
        [
            ("pass", "Pass"),
            ("fail", "Fail"),
            ("conditional", "Conditional Accept"),
        ],
        string="Inspection Result", tracking=True,
    )
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="Related NC")

    notes = fields.Text(string="Notes")
    attachment_ids = fields.Many2many("ir.attachment", string="Attachments")

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.traceability.record") or _("New")
        return super().create(vals_list)


class IatfTraceabilityParameter(models.Model):
    _name = "iatf.traceability.parameter"
    _description = "Process Parameter Measurement"
    _order = "sequence, id"

    record_id = fields.Many2one(
        "iatf.traceability.record", string="Traceability Record",
        required=True, ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Parameter Name", required=True)
    nominal_value = fields.Float(string="Nominal")
    tolerance_upper = fields.Float(string="Upper Tolerance")
    tolerance_lower = fields.Float(string="Lower Tolerance")
    actual_value = fields.Float(string="Actual Value")
    unit = fields.Char(string="Unit")
    in_spec = fields.Boolean(string="In Spec", compute="_compute_in_spec", store=True)

    @api.depends("actual_value", "tolerance_upper", "tolerance_lower")
    def _compute_in_spec(self):
        for rec in self:
            if rec.tolerance_upper and rec.tolerance_lower:
                rec.in_spec = rec.tolerance_lower <= rec.actual_value <= rec.tolerance_upper
            else:
                rec.in_spec = True
