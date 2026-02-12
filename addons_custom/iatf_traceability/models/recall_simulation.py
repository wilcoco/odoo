from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfRecallSimulation(models.Model):
    _name = "iatf.recall.simulation"
    _description = "Recall / Traceability Simulation (IATF 16949 §8.5.2.1)"
    _inherit = ["mail.thread"]
    _order = "simulation_date desc"

    name = fields.Char(string="Simulation Ref", required=True, copy=False, readonly=True,
                        default=lambda self: _("New"))
    simulation_date = fields.Date(string="Simulation Date", default=fields.Date.today, required=True)
    simulation_type = fields.Selection(
        [
            ("forward", "Forward Trace (raw → finished)"),
            ("backward", "Backward Trace (finished → raw)"),
            ("mock_recall", "Mock Recall"),
        ],
        string="Type", required=True, default="backward", tracking=True,
    )

    # ── Starting point ──
    product_id = fields.Many2one("product.product", string="Product", required=True)
    lot_id = fields.Many2one("stock.lot", string="Lot/Serial", required=True)

    # ── Results ──
    affected_lot_ids = fields.Many2many(
        "stock.lot", "iatf_recall_affected_lot_rel", "simulation_id", "lot_id",
        string="Affected Lots",
    )
    affected_production_ids = fields.Many2many(
        "mrp.production", "iatf_recall_affected_mo_rel", "simulation_id", "production_id",
        string="Affected Manufacturing Orders",
    )
    affected_move_ids = fields.Many2many(
        "stock.move", "iatf_recall_affected_move_rel", "simulation_id", "move_id",
        string="Affected Stock Moves",
    )
    affected_partner_ids = fields.Many2many(
        "res.partner", "iatf_recall_affected_partner_rel", "simulation_id", "partner_id",
        string="Affected Customers/Suppliers",
    )

    total_qty_affected = fields.Float(string="Total Qty Affected", readonly=True)
    trace_result = fields.Html(string="Trace Result Summary", readonly=True)
    elapsed_minutes = fields.Float(string="Time Elapsed (min)", help="Time taken to complete the simulation")

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("done", "Completed"),
        ],
        default="draft", tracking=True,
    )

    notes = fields.Text(string="Notes / Observations")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.recall.simulation") or _("New")
        return super().create(vals_list)

    def action_run_trace(self):
        self.ensure_one()
        self.write({"state": "running"})
        import time
        start = time.time()

        lot = self.lot_id
        product = self.product_id

        affected_lots = self.env["stock.lot"]
        affected_mos = self.env["mrp.production"]
        affected_moves = self.env["stock.move"]
        affected_partners = self.env["res.partner"]
        total_qty = 0.0
        lines = []

        if self.simulation_type in ("backward", "mock_recall"):
            # Find MOs that produced this lot
            mos = self.env["mrp.production"].search([
                ("lot_producing_id", "=", lot.id),
            ])
            affected_mos |= mos
            for mo in mos:
                lines.append(_("<li>MO <b>%s</b> produced lot %s</li>") % (mo.name, lot.name))
                # Find raw material lots consumed
                for ml in mo.move_raw_ids.mapped("move_line_ids"):
                    if ml.lot_id:
                        affected_lots |= ml.lot_id
                        lines.append(_("<li>&nbsp;&nbsp;→ Consumed: %s (lot %s) qty %.2f</li>") % (
                            ml.product_id.display_name, ml.lot_id.name, ml.quantity))

            # Find stock moves delivering this lot to customers
            out_moves = self.env["stock.move.line"].search([
                ("lot_id", "=", lot.id),
                ("picking_id.picking_type_code", "=", "outgoing"),
                ("state", "=", "done"),
            ])
            for ml in out_moves:
                if ml.picking_id.partner_id:
                    affected_partners |= ml.picking_id.partner_id
                affected_moves |= ml.move_id
                total_qty += ml.quantity
                lines.append(_("<li>Shipped to <b>%s</b>: qty %.2f (%s)</li>") % (
                    ml.picking_id.partner_id.name if ml.picking_id.partner_id else "N/A",
                    ml.quantity, ml.picking_id.name))

        if self.simulation_type in ("forward", "mock_recall"):
            # Find MOs that consumed this lot as raw material
            consumed_lines = self.env["stock.move.line"].search([
                ("lot_id", "=", lot.id),
                ("production_id", "!=", False),
                ("state", "=", "done"),
            ])
            for ml in consumed_lines:
                mo = ml.production_id
                affected_mos |= mo
                if mo.lot_producing_id:
                    affected_lots |= mo.lot_producing_id
                lines.append(_("<li>Lot %s consumed in MO <b>%s</b> → produced lot %s</li>") % (
                    lot.name, mo.name,
                    mo.lot_producing_id.name if mo.lot_producing_id else "N/A"))

        affected_lots |= lot
        elapsed = (time.time() - start) / 60.0

        summary = "<h3>Trace Results</h3><ul>" + "".join(lines) + "</ul>" if lines else "<p>No trace data found.</p>"

        self.write({
            "state": "done",
            "affected_lot_ids": [(6, 0, affected_lots.ids)],
            "affected_production_ids": [(6, 0, affected_mos.ids)],
            "affected_move_ids": [(6, 0, affected_moves.ids)],
            "affected_partner_ids": [(6, 0, affected_partners.ids)],
            "total_qty_affected": total_qty,
            "trace_result": summary,
            "elapsed_minutes": elapsed,
        })

    def action_reset(self):
        self.write({
            "state": "draft",
            "affected_lot_ids": [(5,)],
            "affected_production_ids": [(5,)],
            "affected_move_ids": [(5,)],
            "affected_partner_ids": [(5,)],
            "total_qty_affected": 0,
            "trace_result": False,
            "elapsed_minutes": 0,
        })
