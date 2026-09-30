"""Synthetic 1.3.1 -> 1.4 migration evidence; only isolated scm_legacy DB."""
import json
from unittest.mock import patch
from odoo import Command, fields
from odoo.exceptions import UserError

assert env.cr.dbname == "cams_night_settlement_scm_legacy", env.cr.dbname
env = env(context=dict(env.context, tracking_disable=True, mail_notrack=True,
    mail_create_nosubscribe=True, mail_notify_force_send=False))
key = "scm_guard.legacy_fixture"
config = env["ir.config_parameter"].sudo()
saved = config.get_param(key)

with patch.object(type(env["purchase.order"]), "_create_portal_notification", lambda *a, **kw: False), \
     patch.object(type(env["mail.mail"]), "send", side_effect=AssertionError("External mail forbidden")):
    if not saved:
        assert env["ir.module.module"].search([("name", "=", "supplier_portal_purchase")]).latest_version == "18.0.1.3.1"
        a = env.company
        b = env["res.company"].create({"name": "SCM synthetic legacy B"})
        vendor = env["res.partner"].create({"name": "SCM synthetic legacy vendor", "supplier_rank": 1,
            "is_supplier_portal": True})
        part = env["product.product"].create({"name": "SCM synthetic legacy part", "type": "consu",
            "is_storable": True, "supplier_taxes_id": [Command.clear()]})
        env["product.supplierinfo"].create({"partner_id": vendor.id, "product_tmpl_id": part.product_tmpl_id.id,
            "company_id": a.id, "price": 10})
        po = env["purchase.order"].create({"partner_id": vendor.id, "company_id": a.id,
            "order_line": [Command.create({"product_id": part.id, "name": part.name,
                "product_uom": part.uom_id.id, "product_qty": 10, "price_unit": 10,
                "date_planned": fields.Datetime.now(), "taxes_id": [Command.clear()]})]})
        po.button_confirm()
        asn = env["supplier.asn"].create({"partner_id": vendor.id,
            "line_ids": [Command.create({"product_id": part.id, "qty": 10})]})
        asn.action_create_picking()
        inventory = env["supplier.inventory"].create({"partner_id": vendor.id,
            "product_id": part.id, "quantity": 5})
        response = env["purchase.order.response"].create({"purchase_order_id": po.id,
            "response_type": "full_accept", "line_response_ids": [Command.create({
                "order_line_id": po.order_line.id, "confirmed_qty": 10,
                "confirmed_date": fields.Date.today()})]})
        duplicate = env["purchase.order.line.response"].create({"response_id": response.id,
            "order_line_id": po.order_line.id, "confirmed_qty": 10})
        forecasts = env["supplier.demand.forecast"].create([
            {"company_id": company, "partner_id": vendor.id, "product_id": part.id,
             "date": fields.Date.today(), "qty_required": qty}
            for company, qty in [(a.id, 10), (a.id, 20), (b.id, 30), (False, 40)]])
        data = {"company": a.id, "other_company": b.id, "vendor": vendor.id,
            "part": part.id, "po": po.id, "asn": asn.id, "picking": asn.picking_id.id,
            "inventory": inventory.id, "response": response.id, "duplicate": duplicate.id,
            "forecast": forecasts.ids}
        config.set_param(key, json.dumps(data))
        env.cr.commit()
        print("SCM_LEGACY_SEEDED " + json.dumps(data, sort_keys=True))
    else:
        data = json.loads(saved)
        if "supplier_portal_company_ids" not in env["res.partner"]._fields:
            # Deliberately inserted duplicate test row only; retain the genuine
            # synthetic statement and record the removed id in the result.
            env["purchase.order.line.response"].browse(data["duplicate"]).unlink()
            env.cr.commit()
            print("SCM_LEGACY_SYNTHETIC_DUPLICATE_REMOVED " + str(data["duplicate"]))
        else:
            checks = []
            assert env["ir.module.module"].search([("name", "=", "supplier_portal_purchase")]).latest_version == "18.0.1.4.0"
            asn = env["supplier.asn"].browse(data["asn"])
            assert asn.company_id.id == data["company"] and asn.picking_id.id == data["picking"]
            checks.append("ASN company inferred from original receipt only")
            before = env["stock.picking"].search_count([])
            try:
                with env.cr.savepoint():
                    asn.action_create_picking()
            except UserError:
                pass
            else:
                raise AssertionError("Unlinked legacy ASN must require reconciliation")
            assert env["stock.picking"].search_count([]) == before
            checks.append("Legacy ASN allocation held without duplicate receipt")
            inventory = env["supplier.inventory"].browse(data["inventory"])
            assert not inventory.company_id and inventory.quantity == 5
            checks.append("Ambiguous inventory retained with no company guessed")
            vendor = env["res.partner"].browse(data["vendor"])
            assert not vendor.supplier_portal_company_ids
            checks.append("No historical vendor company access inferred")
            response = env["purchase.order.response"].browse(data["response"])
            assert not response.request_revision and not response.request_snapshot
            assert len(response.line_response_ids) == 1
            try:
                with env.cr.savepoint():
                    response.purchase_order_id.action_approve_response()
            except UserError:
                pass
            else:
                raise AssertionError("Historical request basis must not be fabricated")
            checks.append("Historical response preserved, no fabricated snapshot/approval")
            forecasts = env["supplier.demand.forecast"].browse(data["forecast"]).exists()
            assert forecasts.ids == data["forecast"][1:3]
            assert forecasts.mapped("qty_required") == [20, 30]
            checks.append("Derived duplicate/null-company forecasts removed; other company preserved")
            cron = env.ref("supplier_portal_purchase.cron_supplier_demand_forecast")
            assert "_cron_generate_all_forecasts" in cron.code
            checks.append("Existing noupdate cron upgraded")
            inventory.company_id = data["company"]
            assert inventory.company_id.id == data["company"] and inventory.quantity == 5
            checks.append("Administrator can explicitly reconcile legacy inventory company")
            env.cr.commit()
            print("SCM_LEGACY_VERIFIED " + json.dumps({"checks": checks, "fixture": data}, sort_keys=True))
