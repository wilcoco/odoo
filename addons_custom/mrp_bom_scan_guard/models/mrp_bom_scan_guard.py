# addons_custom/mrp_bom_scan_guard/models/mrp_bom_scan_guard.py
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class MrpBomScanGuardWizard(models.TransientModel):
    _name = "mrp.bom.scan.guard.wizard"
    _description = "BOM Cross-Check Scanner (Work Order)"

    workorder_id = fields.Many2one("mrp.workorder", string="Work Order", required=True)
    production_id = fields.Many2one(
        "mrp.production", string="Manufacturing Order",
        related="workorder_id.production_id", readonly=True, store=False
    )
    operation_id = fields.Many2one(
        "mrp.routing.workcenter", string="Operation",
        related="workorder_id.operation_id", readonly=True, store=False
    )

    scan_value = fields.Char(
        string="Scan Component",
        help="Scan a component barcode. If 'odoo-qrcode' is installed, this field uses the webcam scanner widget.",
    )
    matched_product_id = fields.Many2one("product.product", string="Matched Product", readonly=True)
    result_state = fields.Selection(
        [
            ("ok", "OK (matches BOM for this MO/operation)"),
            ("wrong_operation", "Component not expected in this operation"),
            ("not_in_bom", "Not in BOM of the MO"),
            ("over_consumed", "Component already fully consumed"),
            ("not_found", "No product with this barcode/default_code"),
        ],
        string="Result", readonly=True
    )
    message = fields.Html(string="Message", sanitize=False, readonly=True)

    allowed_product_ids = fields.Many2many(
        "product.product", string="Expected Components (this operation)",
        compute="_compute_allowed_products", store=False
    )

    # Backend debounce markers to suppress rapid duplicate scans
    last_scan_value = fields.Char(readonly=True)
    last_scan_time = fields.Datetime(readonly=True)

    @api.depends("workorder_id")
    def _compute_allowed_products(self):
        for wiz in self:
            products = wiz._expected_moves_for_operation().mapped("product_id")
            wiz.allowed_product_ids = [(6, 0, products.ids)]

    # ----- helpers -----

    def _expected_moves_for_operation(self):
        """Raw moves that are still relevant for this MO/operation (exclude done/cancel)."""
        self.ensure_one()
        prod = self.production_id
        if not prod:
            return self.env["stock.move"]
        moves = prod.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        # if operation is set on BOM line, restrict to current operation
        if self.operation_id:
            moves = moves.filtered(lambda m: not m.bom_line_id or not m.bom_line_id.operation_id
                                             or m.bom_line_id.operation_id == self.operation_id)
        return moves

    def _find_product_by_scan_value(self, value):
        """Try product by barcode first, then by internal reference(default_code)."""
        Product = self.env["product.product"].sudo()
        product = Product.search([("barcode", "=", value)], limit=1)
        if not product:
            product = Product.search([("default_code", "=", value)], limit=1)
        return product

    def _qty_done_of_move(self, move):
        """Best-effort read of consumed qty on a raw move."""
        qty = 0.0
        # Odoo 18+ uses `quantity` on stock.move and stock.move.line
        if hasattr(move, "quantity") and move.quantity:
            qty = move.quantity
        elif move.move_line_ids:
            qty = sum(move.move_line_ids.mapped("quantity"))
        return qty

    # ----- logging + notification -----

    def _log_and_notify(self):
        """Create a persistent log and send a bus notification on mismatch.

        Note: uses sudo() for creation to avoid UI ACL constraints; read access
        for users will be granted via ir.model.access.
        """
        self.ensure_one()
        if not self.scan_value:
            return
        try:
            Log = self.env["mrp.bom.scan.guard.log"].sudo()
            log = Log.create({
                "workorder_id": self.workorder_id.id,
                "scan_value": self.scan_value,
                "matched_product_id": self.matched_product_id.id if self.matched_product_id else False,
                "result_state": self.result_state or "not_found",
                "message": self.message or False,
            })

            # Only notify on mismatch types
            if self.result_state in ("wrong_operation", "not_in_bom", "not_found"):
                payload = {
                    "log_id": log.id,
                    "workorder_id": self.workorder_id.id,
                    "workorder_name": self.workorder_id.display_name,
                    "production_id": self.production_id.id if self.production_id else False,
                    "production_name": self.production_id.display_name if self.production_id else False,
                    "result_state": self.result_state,
                    "message": self.message,
                    "scan_value": self.scan_value,
                }
                # send to a generic channel that frontend subscribes to
                self.env["bus.bus"]._sendone("mrp_bom_scan_guard", "scan_guard_notification", payload)
        except Exception:
            _logger.exception("Failed to create log/notify: wiz_id=%s", self.id)

    # ----- main logic -----

    @api.onchange("scan_value")
    def _onchange_scan_value(self):
        for wiz in self:
            try:
                code = (wiz.scan_value or "").strip()
                if not code:
                    wiz.matched_product_id = False
                    wiz.result_state = False
                    wiz.message = False
                    wiz.last_scan_value = False
                    wiz.last_scan_time = False
                    continue

                # Duplicate-scan guard within short window
                now = fields.Datetime.now()
                if wiz.last_scan_value and wiz.last_scan_time and wiz.last_scan_value == code:
                    try:
                        now_dt = fields.Datetime.to_datetime(now) if isinstance(now, str) else now
                        last_dt = fields.Datetime.to_datetime(wiz.last_scan_time) if isinstance(wiz.last_scan_time, str) else wiz.last_scan_time
                        delta = (now_dt - last_dt).total_seconds()
                    except Exception:
                        delta = 9999
                    if delta < 2.0:
                        _logger.info("Duplicate scan suppressed within %.3fs: %s (wiz %s)", delta, code, wiz.id)
                        continue

                # Remember last successful scan attempt markers
                wiz.last_scan_value = code
                wiz.last_scan_time = now

                product = wiz._find_product_by_scan_value(code)
                wiz.matched_product_id = product or False

                if not product:
                    wiz.result_state = "not_found"
                    wiz.message = _("<p><b>Not found</b>: No product with barcode/default_code <code>%s</code>.</p>") % code
                    wiz._log_and_notify()
                    continue

                expected_moves = wiz._expected_moves_for_operation()
                move = expected_moves.filtered(lambda m: m.product_id.id == product.id)[:1]
                if not move:
                    # Check if it's in MO BOM (but different operation)
                    in_mo = (
                        wiz.production_id.move_raw_ids if wiz.production_id else wiz.env["stock.move"]
                    ).filtered(lambda m: m.product_id.id == product.id)
                    if in_mo:
                        wiz.result_state = "wrong_operation"
                        wiz.message = _("<p><b>Wrong operation</b>: <code>%s</code> is in MO BOM, but not for this operation.</p>") % (product.display_name,)
                    else:
                        wiz.result_state = "not_in_bom"
                        wiz.message = _("<p><b>Not in BOM</b>: <code>%s</code> is not expected in this MO.</p>") % (product.display_name,)
                    wiz._log_and_notify()
                    continue

                # quantity check
                planned = move.product_uom_qty
                done = wiz._qty_done_of_move(move)
                if done >= planned:
                    wiz.result_state = "over_consumed"
                    wiz.message = _("<p><b>Over-consumed</b>: <code>%s</code> already reached planned qty (%.2f/%.2f).</p>") % (
                        product.display_name, done, planned
                    )
                else:
                    wiz.result_state = "ok"
                    wiz.message = _("<p><b>OK</b>: <code>%s</code> matches BOM for this operation. Consumed: %.2f / Planned: %.2f</p>") % (
                        product.display_name, done, planned
                    )
                # Always log; notify only for mismatches handled in helper
                wiz._log_and_notify()
            except Exception:
                _logger.exception("onchange scan_value failed: wiz_id=%s value=%s", wiz.id, wiz.scan_value)
                wiz.matched_product_id = False
                wiz.result_state = "not_found"
                wiz.message = _(
                    "<p><b>Error</b>: An unexpected error occurred while processing <code>%s</code>. Please retry or contact administrator.</p>"
                ) % (wiz.scan_value or "")
                wiz._log_and_notify()

    def action_reset(self):
        self.write({
            "scan_value": False,
            "matched_product_id": False,
            "result_state": False,
            "message": False,
            "last_scan_value": False,
            "last_scan_time": False,
        })
        return {"type": "ir.actions.do_nothing"}

class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def action_open_bom_scan_guard(self):
        self.ensure_one()
        return {
            "name": _("BOM Scan Guard"),
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom.scan.guard.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_workorder_id": self.id,
            },
        }

    def action_open_scan_guard_logs(self):
        self.ensure_one()
        return {
            "name": _("Scan Guard Logs"),
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom.scan.guard.log",
            "view_mode": "list,form",
            "target": "current",
            "domain": [("workorder_id", "=", self.id)],
            "context": {"search_default_mismatch": 0},
        }