from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref("supplier_portal_purchase.cron_supplier_demand_forecast", raise_if_not_found=False)
    if cron:
        cron.code = "model._cron_generate_all_forecasts()"
    # Never infer portal company grants from a mere trading relationship, and
    # never fabricate historical response snapshots from today's PO/BOM values.
