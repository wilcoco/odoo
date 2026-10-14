import datetime
from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command, api, fields
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.supplier_portal_purchase.controllers import portal


@tagged("post_install", "-at_install")
class TestScmGuard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, mail_notrack=True,
            mail_create_nosubscribe=True, mail_notify_force_send=False))
        cls.company = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "SCM guard B"})
        cls.wh = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.wh_b = cls.env["stock.warehouse"].create({"name": "SCM guard B stock", "code": "SGDB",
            "company_id": cls.company_b.id})
        cls.vendor = cls.env["res.partner"].create({"name": "SCM guard vendor", "supplier_rank": 1,
            "is_supplier_portal": True, "supplier_portal_company_ids": [Command.set(cls.company.ids)]})
        cls.other = cls.env["res.partner"].create({"name": "SCM guard other", "supplier_rank": 1,
            "is_supplier_portal": True, "supplier_portal_company_ids": [Command.set(cls.company.ids)]})
        cls.part = cls.env["product.product"].create({"name": "SCM guarded component", "type": "consu",
            "is_storable": True, "supplier_taxes_id": [Command.clear()]})
        cls.fg = cls.env["product.product"].create({"name": "SCM guarded FG", "type": "consu"})
        cls.env["product.supplierinfo"].create({"product_tmpl_id": cls.part.product_tmpl_id.id,
            "partner_id": cls.vendor.id, "price": 10, "company_id": cls.company.id})
        cls.bom = cls.env["mrp.bom"].create({"product_tmpl_id": cls.fg.product_tmpl_id.id,
            "product_id": cls.fg.id, "product_qty": 1, "company_id": cls.company.id,
            "bom_line_ids": [Command.create({"product_id": cls.part.id, "product_qty": 2})]})
        cls.portal_user = cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": "SCM guard portal", "login": "scm-guard-portal", "partner_id": cls.vendor.id,
            "company_id": cls.company.id, "company_ids": [Command.set(cls.company.ids)],
            "groups_id": [Command.set(cls.env.ref("base.group_portal").ids)]})

    def setUp(self):
        super().setUp()
        self.notification_patch = patch.object(type(self.env["purchase.order"]), "_create_portal_notification", lambda *a, **kw: False)
        self.notification_patch.start()
        self.addCleanup(self.notification_patch.stop)
        self.mail_patch = patch.object(type(self.env["mail.mail"]), "send", side_effect=AssertionError("External send forbidden"))
        self.mail_patch.start()
        self.addCleanup(self.mail_patch.stop)

    def po(self, qty=20, company=None):
        company = company or self.company
        return self.env["purchase.order"].with_company(company).create({"partner_id": self.vendor.id,
            "company_id": company.id, "picking_type_id": (self.wh if company == self.company else self.wh_b).in_type_id.id,
            "order_line": [Command.create({"name": self.part.name, "product_id": self.part.id,
                "product_qty": qty, "product_uom": self.part.uom_id.id, "price_unit": 10,
                "date_planned": fields.Datetime.now(), "taxes_id": [Command.clear()]})]})

    def asn(self, po, qty=10):
        return self.env["supplier.asn"].create({"partner_id": self.vendor.id,
            "line_ids": [Command.create({"product_id": self.part.id, "qty": qty,
                "purchase_line_id": po.order_line.id})]})

    def fake_request(self):
        req = SimpleNamespace(env=api.Environment(self.env.cr, self.portal_user.id,
            dict(self.env.context, allowed_company_ids=self.company.ids)), redirect=lambda value: value,
            render=lambda template, values: values)
        req.update_env = lambda context=None, **kw: setattr(req, "env", req.env(context=context))
        return req

    def response(self, po, qty=None):
        return self.env["purchase.order.response"].create({"purchase_order_id": po.id,
            "response_type": "full_accept", "line_response_ids": [Command.create({
                "order_line_id": po.order_line.id, "confirmed_qty": po.order_line.product_qty if qty is None else qty,
                "confirmed_date": po.order_line.date_planned.date()})]})

    def test_forecast_company_rebuild_preserves_other_company(self):
        today = fields.Date.today()
        for company, qty in [(self.company, 10), (self.company_b, 20)]:
            self.env["production.demand"].with_company(company).create({"product_id": self.fg.id,
                "demand_date": today, "quantity": qty, "company_id": company.id})
        other = self.env["supplier.demand.forecast"].with_company(self.company_b).create({
            "company_id": self.company_b.id, "partner_id": self.vendor.id, "product_id": self.part.id,
            "date": today, "qty_required": 40})
        self.env["supplier.demand.forecast"].cron_generate_forecast()
        rows = self.env["supplier.demand.forecast"].search([("company_id", "=", self.company.id),
            ("product_id", "=", self.part.id)])
        self.assertEqual(rows.qty_required, 20)
        self.assertTrue(other.exists())
        self.assertEqual(other.qty_required, 40)

    def test_forecast_late_receipt_does_not_cover_today(self):
        po = self.po()
        po.button_confirm()
        future = fields.Date.add(fields.Date.today(), days=10)
        po.picking_ids.move_ids.date = str(future) + " 10:00:00"
        self.env["production.demand"].create({"product_id": self.fg.id, "quantity": 10,
            "demand_date": fields.Date.today()})
        self.env["supplier.demand.forecast"].cron_generate_forecast()
        row = self.env["supplier.demand.forecast"].search([("product_id", "=", self.part.id)])
        self.assertEqual((row.qty_incoming, row.qty_shortfall), (0, 20))
        self.assertEqual(self.env["supplier.supply.status"]._part_blocks(self.vendor)[0]["alert"]["level"], "danger")

    def test_forecast_quarantine_outside_stock_not_available(self):
        location = self.env["stock.location"].create({"name": "SCM IQC awaiting", "usage": "internal",
            "location_id": self.wh.view_location_id.id, "company_id": self.company.id})
        self.env["stock.quant"]._update_available_quantity(self.part, location, 30)
        self.env["production.demand"].create({"product_id": self.fg.id, "quantity": 10,
            "demand_date": fields.Date.today()})
        self.env["supplier.demand.forecast"].cron_generate_forecast()
        row = self.env["supplier.demand.forecast"].search([("product_id", "=", self.part.id)])
        self.assertEqual((row.qty_onhand, row.qty_shortfall), (0, 20))

    def test_fresh_sufficient_snapshot_is_not_falsely_stale(self):
        self.env["stock.quant"]._update_available_quantity(self.part, self.wh.lot_stock_id, 30)
        self.env["production.demand"].create({"product_id": self.fg.id, "quantity": 10,
            "demand_date": fields.Date.today()})
        self.env["supplier.demand.forecast"].cron_generate_forecast()
        block = self.env["supplier.supply.status"]._part_blocks(self.vendor)[0]
        self.assertFalse(block["refresh_required"])
        self.assertEqual(block["alert"]["level"], "ok")

    def test_stale_snapshot_needs_confirmation_without_invented_expiry(self):
        self.env["production.demand"].create({"product_id": self.fg.id, "quantity": 10,
            "demand_date": fields.Date.today()})
        self.env["supplier.demand.forecast"].cron_generate_forecast()
        rows = self.env["supplier.demand.forecast"].search([("product_id", "=", self.part.id)])
        rows.write({"snapshot_at": fields.Datetime.now() - datetime.timedelta(days=90), "qty_shortfall": 0})
        block = self.env["supplier.supply.status"]._part_blocks(self.vendor)[0]
        self.assertTrue(block["refresh_required"])
        self.assertEqual(block["alert"]["level"], "warning")

    def test_other_company_notification_does_not_suppress_own_shortfall(self):
        Notification = self.env["supplier.portal.notification"]
        Notification.with_company(self.company_b).create({"partner_id": self.vendor.id,
            "product_id": self.part.id, "notification_type": "replenish_request"})
        self.env["supplier.demand.forecast"].create({"company_id": self.company.id,
            "partner_id": self.vendor.id, "product_id": self.part.id,
            "date": fields.Date.today(), "qty_required": 10, "qty_shortfall": 10})
        self.assertEqual(self.env["supplier.supply.status"].cron_notify_replenishment(), 1)
        self.assertEqual(self.env["supplier.supply.status"].cron_notify_replenishment(), 0)
        rows = Notification.search([("partner_id", "=", self.vendor.id),
            ("notification_type", "=", "replenish_request")])
        self.assertEqual(set(rows.company_id.ids), {self.company.id, self.company_b.id})

    def test_asn_repeat_single_receipt_and_po_quantity(self):
        po = self.po()
        po.button_confirm()
        asn = self.asn(po)
        first = asn.action_create_picking()["res_id"]
        self.assertEqual(asn.action_create_picking()["res_id"], first)
        picking = self.env["stock.picking"].browse(first)
        self.assertEqual(picking.move_ids.purchase_line_id, po.order_line)
        picking.move_ids.write({"quantity": 10, "picked": True})
        picking.button_validate()
        self.assertEqual((po.order_line.qty_received, asn.state), (10, "received"))
        self.assertEqual(asn.action_create_picking()["res_id"], first)
        self.assertEqual(sum(po.picking_ids.move_ids.filtered(lambda m: m.state != "cancel").mapped("product_qty")), 20)

    def test_asn_product_uom_allocation_preserves_purchase_uom(self):
        po = self.po(2)
        po.order_line.product_uom = self.env.ref("uom.product_uom_dozen")
        po.button_confirm()
        asn = self.asn(po, qty=12)
        picking = self.env["stock.picking"].browse(asn.action_create_picking()["res_id"])
        self.assertEqual(sum(picking.move_ids.mapped("product_qty")), 12)
        picking.move_ids.picked = True
        picking.button_validate()
        self.assertEqual(po.order_line.qty_received, 1)
        self.assertEqual(asn.state, "received")

    def test_asn_partial_receipt_returns_same_backorder(self):
        po = self.po()
        po.button_confirm()
        asn = self.asn(po)
        picking = self.env["stock.picking"].browse(asn.action_create_picking()["res_id"])
        picking.move_ids.write({"quantity": 6, "picked": True})
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual((po.order_line.qty_received, asn.state), (6, "announced"))
        backorder = self.env["stock.picking"].browse(asn.action_create_picking()["res_id"])
        self.assertNotEqual(backorder, picking)
        self.assertEqual(backorder.backorder_id, picking)
        self.assertEqual(sum(backorder.move_ids.mapped("product_qty")), 4)
        backorder.move_ids.write({"quantity": 4, "picked": True})
        backorder.button_validate()
        self.assertEqual((po.order_line.qty_received, asn.state), (10, "received"))
        with self.assertRaises(UserError):
            asn.action_cancel()

    def test_asn_cancellation_releases_po_obligation(self):
        po = self.po()
        po.button_confirm()
        asn = self.asn(po)
        asn.action_create_picking()
        asn.action_cancel()
        self.assertEqual(asn.state, "cancelled")
        self.assertFalse(asn.line_ids.move_ids)
        self.assertEqual(sum(po.picking_ids.move_ids.filtered(lambda m: m.state != "cancel").mapped("product_qty")), 20)
        with self.assertRaises(UserError):
            asn.action_create_picking()
        new_asn = self.asn(po)
        self.assertTrue(new_asn.action_create_picking()["res_id"])

    def test_asn_no_source_and_wrong_source_rejected(self):
        asn = self.env["supplier.asn"].create({"partner_id": self.vendor.id,
            "line_ids": [Command.create({"product_id": self.part.id, "qty": 10})]})
        with self.assertRaises(UserError):
            asn.action_create_picking()
        other_po = self.po(company=self.company_b)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            asn.line_ids.purchase_line_id = other_po.order_line

    def test_asn_evidence_cannot_be_detached_or_deleted(self):
        po = self.po()
        po.button_confirm()
        asn = self.asn(po)
        asn.action_create_picking()
        for operation in [lambda: asn.line_ids.move_ids.write({"supplier_asn_line_id": False}),
                          asn.unlink, asn.line_ids.unlink]:
            with self.assertRaises(UserError):
                operation()
        self.assertTrue(asn.line_ids.move_ids)

    def test_asn_cannot_overallocate_same_po_remainder(self):
        po = self.po(10)
        po.button_confirm()
        self.asn(po).action_create_picking()
        other = self.asn(po)
        with self.assertRaises(UserError), self.cr.savepoint():
            other.action_create_picking()
        self.assertFalse(other.picking_id)

    def test_portal_company_and_grant_enforced(self):
        po = self.po()
        other_po = self.po(company=self.company_b)
        req = self.fake_request()
        with patch.object(portal, "request", req):
            controller = portal.SupplierPortalController()
            self.assertEqual(controller._validate_po_access(po.id, None)[1].id, po.id)
            with self.assertRaises(AccessDenied):
                controller._validate_po_access(other_po.id, None)
            self.vendor.supplier_portal_company_ids = [Command.clear()]
            with self.assertRaises(AccessDenied):
                controller._validate_portal_access(None)

    def test_inventory_model_rejects_invalid_quantity_and_partner_product(self):
        Model = self.env["supplier.inventory"]
        for qty in [-1, float("inf"), float("nan")]:
            with self.assertRaises(ValidationError), self.cr.savepoint():
                Model.create({"partner_id": self.vendor.id, "product_id": self.part.id, "quantity": qty})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            Model.create({"partner_id": self.other.id, "product_id": self.part.id, "quantity": 1})
        valid = Model.create({"partner_id": self.vendor.id, "product_id": self.part.id, "quantity": 0})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            valid.quantity = -1

    def test_inventory_portal_cannot_write_other_supplier_or_company(self):
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["supplier.inventory"].with_user(self.portal_user).create({
                "partner_id": self.other.id, "product_id": self.part.id, "quantity": 1})
        with self.assertRaises(AccessError), self.cr.savepoint():
            self.env["supplier.inventory"].with_user(self.portal_user).sudo().create({
                "partner_id": self.vendor.id, "company_id": self.company_b.id,
                "product_id": self.part.id, "quantity": 1})

    def test_inventory_controller_invalid_payload_leaves_no_record(self):
        req = self.fake_request()
        with patch.object(portal, "request", req):
            controller = portal.SupplierPortalController()
            result = controller.update_my_inventory(product_id=str(self.part.id), quantity="nan")
        self.assertIn("invalid_inventory", result if isinstance(result, str) else result.get_data(as_text=True))
        self.assertFalse(self.env["supplier.inventory"].search([("partner_id", "=", self.vendor.id)]))

    def test_supplier_cannot_forge_inventory_confirmation_time(self):
        future = fields.Datetime.now() + datetime.timedelta(days=900)
        record = self.env["supplier.inventory"].with_user(self.portal_user).sudo().with_context(
            default_last_updated=future).create({"partner_id": self.vendor.id,
                "product_id": self.part.id, "quantity": 7, "last_updated": future})
        self.assertLess(record.last_updated, future)
        with self.assertRaises(UserError):
            record.write({"last_updated": future})
        record.write({"quantity": 8, "last_updated": future})
        self.assertLess(record.last_updated, future)

    def test_request_revision_preserves_history_and_blocks_stale_approval(self):
        po = self.po(100)
        response = self.response(po)
        revision = response.request_revision
        po.order_line.product_qty = 200
        self.assertEqual(response.line_response_ids.requested_qty, 100)
        self.assertEqual(response.request_revision, revision)
        with self.assertRaises(UserError):
            po.action_approve_response()
        self.assertEqual(po.order_line.product_qty, 200)

    def test_response_approval_records_reviewer_and_locks_evidence(self):
        po = self.po(10)
        response = self.response(po)
        po.action_approve_response()
        self.assertEqual(response.review_state, "approved")
        self.assertEqual(response.reviewed_by, self.env.user)
        self.assertTrue(response.reviewed_date)
        for operation in [lambda: response.write({"review_state": "pending"}),
                          lambda: response.line_response_ids.write({"confirmed_qty": 20}),
                          response.line_response_ids.unlink]:
            with self.assertRaises(UserError):
                operation()

    def test_response_cannot_reference_other_orders_line(self):
        po = self.po()
        other = self.po()
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env["purchase.order.response"].create({"purchase_order_id": po.id,
                "response_type": "full_accept", "line_response_ids": [Command.create({
                    "order_line_id": other.order_line.id, "confirmed_qty": 20})]})
