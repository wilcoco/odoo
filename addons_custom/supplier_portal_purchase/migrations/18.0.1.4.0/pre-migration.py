"""Do not assign existing ambiguous supplier data to the installer's company."""


def migrate(cr, version):
    cr.execute("""SELECT response_id, order_line_id FROM purchase_order_line_response
                  GROUP BY response_id, order_line_id HAVING count(*) > 1 LIMIT 1""")
    if cr.fetchone():
        # These are supplier statements, unlike replaceable forecast snapshots.
        # Never discard evidence merely to make a unique constraint install.
        raise RuntimeError("SCM upgrade needs review: duplicate supplier response lines exist; "
                           "reconcile and preserve their history before retrying the upgrade.")
    for table in ("supplier_asn", "supplier_asn_line", "supplier_inventory", "supplier_order",
                  "supplier_portal_notification", "purchase_order_response", "purchase_order_line_response",
                  "supply_chain_order", "supply_chain_order_status"):
        cr.execute("ALTER TABLE " + table + " ADD COLUMN IF NOT EXISTS company_id integer")
    cr.execute("""UPDATE supplier_asn a SET company_id=p.company_id
                  FROM stock_picking p WHERE a.picking_id=p.id AND a.company_id IS NULL""")
    cr.execute("""UPDATE supplier_portal_notification n SET company_id=p.company_id
                  FROM purchase_order p WHERE n.purchase_order_id=p.id AND n.company_id IS NULL""")
    cr.execute("""UPDATE supplier_order o SET company_id=p.company_id
                  FROM supply_chain_order c JOIN purchase_order p ON p.id=c.purchase_order_id
                  WHERE o.chain_order_id=c.id AND o.company_id IS NULL""")
    # Establish the same source-derived company before Odoo recomputes related
    # fields/constraints; related model recomputation order is not guaranteed.
    cr.execute("""UPDATE supplier_asn_line l SET company_id=a.company_id
                  FROM supplier_asn a WHERE l.asn_id=a.id AND l.company_id IS NULL""")
    cr.execute("""UPDATE purchase_order_response r SET company_id=p.company_id
                  FROM purchase_order p WHERE r.purchase_order_id=p.id AND r.company_id IS NULL""")
    cr.execute("""UPDATE purchase_order_line_response l SET company_id=r.company_id
                  FROM purchase_order_response r WHERE l.response_id=r.id AND l.company_id IS NULL""")
    cr.execute("""UPDATE supply_chain_order c SET company_id=p.company_id
                  FROM purchase_order p WHERE c.purchase_order_id=p.id AND c.company_id IS NULL""")
    cr.execute("""UPDATE supply_chain_order_status s SET company_id=c.company_id
                  FROM supply_chain_order c WHERE s.chain_order_id=c.id AND s.company_id IS NULL""")
    # Forecasts are derived snapshots, not a stock/accounting/evidence ledger.
    # Discard only ambiguous/duplicate derived rows before the scoped unique key.
    cr.execute("DELETE FROM supplier_demand_forecast WHERE company_id IS NULL")
    cr.execute("""DELETE FROM supplier_demand_forecast a USING supplier_demand_forecast b
                  WHERE a.company_id=b.company_id AND a.partner_id=b.partner_id
                  AND a.product_id=b.product_id AND a.date=b.date AND a.id<b.id""")
