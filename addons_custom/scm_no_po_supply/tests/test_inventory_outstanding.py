"""무발주 소요통보 잔량이 협력사 재고 '미입고 요구량'에 포함되는지."""
import json
from datetime import date, timedelta

from odoo import Command
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInventoryOutstandingWithNotice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, mail_notrack=True,
                                       mail_create_nosubscribe=True, mail_notify_force_send=False))
        cls.company = cls.env.company
        cls.vendor = cls.env["res.partner"].create({
            "name": "NOPO-INV 협력사", "supplier_rank": 1, "email": "nopo-inv@example.com",
            "is_supplier_portal": True, "supplier_portal_company_ids": [Command.set(cls.company.ids)]})
        category = cls.env["product.category"].create({"name": "NOPO-INV manual valuation", "property_valuation": "manual_periodic"})
        cls.part = cls.env["product.product"].create({"name": "NOPO-INV 부품", "default_code": "NOPOINV-P", "type": "consu",
                                                      "is_storable": True, "categ_id": category.id, "standard_price": 10})
        cls.env["product.supplierinfo"].create({"partner_id": cls.vendor.id, "product_tmpl_id": cls.part.product_tmpl_id.id,
                                                "company_id": cls.company.id, "price": 50})
        wh = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.agreement = cls.env["scm.no.po.agreement"].create({
            "name": "NOPO-INV 협약", "company_id": cls.company.id, "partner_id": cls.vendor.id, "product_id": cls.part.id,
            "picking_type_id": wh.in_type_id.id, "reference": "NOPO-INV 협약서", "component_confirmed": True,
            "date_start": "2026-01-01", "date_end": "2026-12-31", "active": True})

    def _notice(self, qty):
        notice = self.env["scm.no.po.notice"].create({
            "name": "NOPO-INV 통보 %s" % qty, "agreement_id": self.agreement.id, "uom_id": self.part.uom_id.id,
            "quantity": qty, "need_date": date.today() + timedelta(days=7),
            "source_reference": json.dumps({"test": "outstanding"}), "source_kind": "manual"})
        notice.action_issue()
        return notice

    def test_issued_notice_counts_as_outstanding(self):
        inv = self.env["supplier.inventory"].create({"company_id": self.company.id, "partner_id": self.vendor.id,
                                                     "product_id": self.part.id, "quantity": 2})
        self.assertEqual(inv.outstanding_qty, 0)
        self._notice(4)
        inv.invalidate_recordset()
        self.assertEqual((inv.outstanding_qty, inv.shortage_qty, inv.needs_update), (4, 2, True))
        inv.write({"quantity": 10})
        inv.invalidate_recordset()
        self.assertFalse(inv.needs_update)
