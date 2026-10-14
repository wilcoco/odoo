"""Committed synthetic two-transaction acceptance; run only in the named disposable DB.

Not imported by the normal Odoo test suite: TransactionCase's shared test cursor
cannot prove real row-lock waiting, commit visibility or whole-request recovery.
The runtime shell loads this file from the frozen candidate's /experiment mount.
"""
import json
import threading
import time
import traceback
import uuid
from unittest.mock import patch

from psycopg2 import errors

from odoo import api, Command, SUPERUSER_ID
from odoo.exceptions import UserError


class InjectedRollback(Exception):
    """Simulated caller failure after the service has completed but before commit."""


def _run(shell_env):
    assert shell_env.cr.dbname == "cams_night_settlement_scm_guard", "Disposable concurrency DB only"
    registry = shell_env.registry
    run_key = uuid.uuid4().hex[:8]
    ctx = {"allowed_company_ids": [shell_env.company.id], "tracking_disable": True,
           "mail_create_nosubscribe": True, "mail_notrack": True}
    company_id = shell_env.company.id
    result = {"database": shell_env.cr.dbname, "run_key": run_key, "scenarios": [],
              "test_method": "independent worker cursors/transactions, observed PostgreSQL row-lock blocking"}

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, ctx)
        user = env["res.users"].with_context(no_reset_password=True).create({
            "name": "SYNTHETIC ASN operator " + run_key, "login": "synthetic-asn-" + run_key,
            "company_id": company_id, "company_ids": [Command.set([company_id])],
            "groups_id": [Command.set([env.ref("base.group_user").id,
                env.ref("purchase.group_purchase_user").id, env.ref("stock.group_stock_user").id])],
        })
        actor_id = user.id
        cr.commit()
    shell_env.cr.rollback()

    def fixture(scenario):
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, ctx)
            vendor = env["res.partner"].create({"name": "SYNTHETIC ASN vendor " + run_key + scenario,
                "supplier_rank": 1, "is_supplier_portal": True})
            part = env["product.product"].create({"name": "SYNTHETIC ASN component " + scenario,
                "type": "consu", "is_storable": True, "supplier_taxes_id": [Command.clear()]})
            env["product.supplierinfo"].create({"product_tmpl_id": part.product_tmpl_id.id,
                "partner_id": vendor.id, "company_id": company_id, "price": 1})
            po = env["purchase.order"].create({"partner_id": vendor.id, "company_id": company_id,
                "order_line": [Command.create({"name": part.name, "product_id": part.id,
                    "product_qty": 10, "product_uom": part.uom_id.id, "price_unit": 1,
                    "date_planned": "2026-09-10 00:00:00", "taxes_id": [Command.clear()]})]})
            po.button_confirm()
            def asn():
                return env["supplier.asn"].create({"partner_id": vendor.id, "company_id": company_id,
                    "line_ids": [Command.create({"product_id": part.id, "qty": 10,
                        "purchase_line_id": po.order_line.id})]})
            first = asn()
            second = asn() if scenario.startswith("competing_asn") else first
            ids = {"first": first.id, "second": second.id, "po": po.id, "part": part.id}
            cr.commit()
            return ids

    def operation(env, ids, kind, label="follower"):
        asn_id = ids["first" if label == "leader" else "second"]
        return [env["supplier.asn"].browse(asn_id).action_create_picking()["res_id"]]

    def transact(ids, kind):
        with registry.cursor() as cr:
            value = operation(api.Environment(cr, actor_id, ctx), ids, kind)
            cr.commit()
            return value

    def observe(ids):
        with registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, ctx)
            po = env["purchase.order"].browse(ids["po"])
            moves = po.picking_ids.move_ids.filtered(lambda m: m.state != "cancel")
            allocated = moves.filtered("supplier_asn_line_id")
            quants = env["stock.quant"].search([("product_id", "=", ids["part"]),
                ("location_id.usage", "=", "internal"), ("company_id", "=", company_id)])
            return {"po_move_ids": moves.ids, "po_expected_qty": sum(moves.mapped("product_qty")),
                "asn_ids": allocated.supplier_asn_line_id.asn_id.ids,
                "allocated_qty": sum(allocated.mapped("product_qty")),
                "picking_ids": allocated.picking_id.ids,
                "received_qty": po.order_line.qty_received, "internal_stock": sum(quants.mapped("quantity"))}

    def scenario(kind, first_rolls_back):
        name = kind + ("_first_rollback" if first_rolls_back else "_first_commit")
        ids = fixture(name)
        report = {"name": name, "workers": {}, "retry": None}
        held = threading.Event()
        follower_ready = threading.Event()
        release = threading.Event()
        errors_seen = []

        def worker(label):
            data = report["workers"][label] = {}
            try:
                with registry.cursor() as cr:
                    cr.execute("SET LOCAL lock_timeout = '12s'")
                    cr.execute("SET LOCAL statement_timeout = '20s'")
                    cr.execute("SELECT pg_backend_pid(), txid_current(), current_setting('transaction_isolation')")
                    pid, txid, isolation = cr.fetchone()
                    data.update(pid=pid, txid=txid, isolation=isolation)
                    env = api.Environment(cr, actor_id, ctx)
                    if label == "follower":
                        assert held.wait(15), "leader did not reach uncommitted result"
                        # Establish a real old snapshot before trying the same service.
                        table = "supplier_asn"
                        cr.execute("SELECT count(*) FROM " + table)
                        data["snapshot_row_count"] = cr.fetchone()[0]
                        follower_ready.set()
                    value = operation(env, ids, kind, label=label)
                    env.flush_all()
                    data["result_ids"] = value
                    if label == "leader":
                        held.set()
                        assert release.wait(15), "observer did not release leader"
                        if first_rolls_back:
                            raise InjectedRollback("SYNTHETIC failure after result, before commit")
                    cr.commit()
                    data["outcome"] = "committed"
            except (errors.SerializationFailure, InjectedRollback, UserError) as error:
                data.update(outcome="rolled_back", exception=type(error).__name__,
                            sqlstate=getattr(error, "pgcode", None), message=str(error))
            except BaseException:
                data.update(outcome="unexpected_error", traceback=traceback.format_exc())
                errors_seen.append(data["traceback"])
                held.set()
                follower_ready.set()

        leader = threading.Thread(target=worker, args=("leader",), name=name + "-leader", daemon=True)
        follower = threading.Thread(target=worker, args=("follower",), name=name + "-follower", daemon=True)
        leader.start()
        follower.start()
        try:
            assert follower_ready.wait(15), "follower did not start its separate transaction"
            deadline = time.monotonic() + 10
            observed = None
            while time.monotonic() < deadline:
                leader_data, follower_data = report["workers"]["leader"], report["workers"]["follower"]
                assert not errors_seen, errors_seen
                with registry.cursor() as monitor:
                    monitor.execute("SELECT pg_blocking_pids(%s)", [follower_data["pid"]])
                    blockers = monitor.fetchone()[0]
                if leader_data["pid"] in blockers:
                    observed = {"blocked_pid": follower_data["pid"], "blocking_pids": blockers}
                    break
                time.sleep(0.025)
            assert observed, "did not observe actual row-lock contention; sequential calls do not count"
            report["observed_lock_wait"] = observed
        finally:
            release.set()
            leader.join(25)
            follower.join(25)
        assert not leader.is_alive() and not follower.is_alive(), "worker did not finish"
        assert not errors_seen, errors_seen
        first, second = report["workers"]["leader"], report["workers"]["follower"]
        assert first["pid"] != second["pid"] and first["txid"] != second["txid"], report
        assert first["isolation"] == second["isolation"] == "repeatable read", report
        if first_rolls_back:
            assert first.get("exception") == "InjectedRollback", report
            assert second["outcome"] == "committed", report
        else:
            assert first["outcome"] == "committed", report
            # Odoo uses repeatable read: a loser must abort its whole transaction,
            # then retry with a fresh snapshot; a savepoint-only retry is unsafe.
            assert second.get("sqlstate") == "40001", report
            try:
                report["retry"] = {"outcome": "committed", "ids": transact(ids, kind)}
            except UserError as error:
                report["retry"] = {"outcome": "already_allocated", "message": str(error)}
            assert report["retry"]["outcome"] == ("committed" if kind == "same_asn" else "already_allocated"), report
            if kind == "same_asn":
                assert report["retry"]["ids"] == first["result_ids"], report
        report["reconciliation_before_receipt"] = observe(ids)
        totals = report["reconciliation_before_receipt"]
        assert len(totals["asn_ids"]) == len(totals["picking_ids"]) == 1, report
        assert totals["po_expected_qty"] == totals["allocated_qty"] == 10, report
        assert totals["received_qty"] == totals["internal_stock"] == 0, report
        with registry.cursor() as cr:
            env = api.Environment(cr, actor_id, ctx)
            picking = env["stock.picking"].browse(totals["picking_ids"])
            picking.move_ids.write({"quantity": 10, "picked": True})
            picking.button_validate()
            assert picking.state == "done"
            cr.commit()
        report["reconciliation_after_receipt"] = observe(ids)
        assert report["reconciliation_after_receipt"]["received_qty"] == 10, report
        assert report["reconciliation_after_receipt"]["internal_stock"] == 10, report
        report["status"] = "PASS"
        result["scenarios"].append(report)
        print("ASN_CONCURRENCY_SCENARIO " + json.dumps(report, ensure_ascii=False), flush=True)
        return ids

    for kind in ("same_asn", "competing_asn"):
        for first_rolls_back in (False, True):
            scenario(kind, first_rolls_back)
    result.update(status="PASS", concurrency_scenarios=4)
    print("ASN_CONCURRENCY_RESULT " + json.dumps(result, ensure_ascii=False), flush=True)
    return result


def run(env):
    with patch.object(type(env["mail.mail"]), "send", side_effect=AssertionError("External send forbidden")), \
            patch.object(type(env["purchase.order"]), "_create_portal_notification", lambda *a, **kw: False):
        return _run(env)
