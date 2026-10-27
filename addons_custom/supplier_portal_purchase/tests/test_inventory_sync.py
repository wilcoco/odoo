"""협력사 신고 재고 ↔ 납품 연동: 입고 확정 시 차감(멱등·0 하한), 부족 시 갱신 요청 알림·메일 (2026-10-19 사용자 결정)."""
from odoo import Command
from odoo.tests import HttpCase, TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSupplierInventorySync(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vendor = cls.env["res.partner"].create({
            "name": "INV-SYNC 협력사", "supplier_rank": 1, "email": "inv-sync@example.com",
            "is_supplier_portal": True, "supplier_portal_company_ids": [Command.set(cls.company.ids)]})
        cls.plain_vendor = cls.env["res.partner"].create({"name": "INV-SYNC 일반 공급사", "supplier_rank": 1})
        cls.part = cls.env["product.product"].create({"name": "INV-SYNC 부품", "default_code": "INVSYNC-P", "type": "consu", "is_storable": True})
        for vendor in (cls.vendor, cls.plain_vendor):
            cls.env["product.supplierinfo"].create({"partner_id": vendor.id, "product_tmpl_id": cls.part.product_tmpl_id.id,
                                                    "company_id": cls.company.id, "price": 100})
        cls.Inventory = cls.env["supplier.inventory"]
        cls.Notification = cls.env["supplier.portal.notification"]

    def _inventory(self, qty, vendor=None):
        return self.Inventory.create({"company_id": self.company.id, "partner_id": (vendor or self.vendor).id,
                                      "product_id": self.part.id, "quantity": qty})

    def _po(self, qty, vendor=None):
        po = self.env["purchase.order"].create({
            "partner_id": (vendor or self.vendor).id, "company_id": self.company.id,
            "order_line": [Command.create({"name": self.part.name, "product_id": self.part.id, "product_qty": qty,
                                           "product_uom": self.part.uom_id.id, "price_unit": 100})]})
        po.button_confirm()
        return po

    def _receive(self, po, qty):
        picking = po.picking_ids.filtered(lambda p: p.state not in ("done", "cancel"))[:1]
        picking.move_ids.write({"quantity": qty, "picked": True})
        picking.with_context(skip_backorder=True).button_validate()
        self.assertEqual(picking.state, "done")
        return picking

    def test_outstanding_is_open_po_quantity(self):
        inv = self._inventory(10)
        self.assertEqual(inv.outstanding_qty, 0)
        self._po(6)
        inv.invalidate_recordset()
        self.assertEqual((inv.outstanding_qty, inv.shortage_qty, inv.needs_update), (6, 0, False))

    def test_receipt_deducts_once_and_updates_outstanding(self):
        inv = self._inventory(10)
        po = self._po(6)
        picking = self._receive(po, 4)
        inv.invalidate_recordset()
        self.assertEqual(inv.quantity, 6, "입고 확정 4 → 신고 재고 10-4")
        self.assertEqual(inv.last_deduction_qty, 4)
        self.assertTrue(picking.move_ids.supplier_inventory_deducted)
        self.assertEqual(inv.outstanding_qty, 2)
        self.assertFalse(inv.needs_update)
        # 같은 이동으로 다시 차감하지 않는다
        self.Inventory._deduct_for_receipt(picking.move_ids)
        inv.invalidate_recordset()
        self.assertEqual(inv.quantity, 6)
        self.assertFalse(self.Notification.search([("partner_id", "=", self.vendor.id), ("notification_type", "=", "inventory_update")]))

    def test_shortage_after_deduction_notifies_supplier_once(self):
        inv = self._inventory(5)
        po = self._po(6)
        mails_before = self.env["mail.mail"].search_count([("model", "=", "supplier.inventory")])
        self._receive(po, 3)
        inv.invalidate_recordset()
        self.assertEqual((inv.quantity, inv.outstanding_qty, inv.shortage_qty, inv.needs_update), (2, 3, 1, True))
        notes = self.Notification.search([("partner_id", "=", self.vendor.id), ("notification_type", "=", "inventory_update")])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes.product_id, self.part)
        self.assertIn("재고 갱신 요청", notes.message)
        self.assertTrue(inv.update_requested_at)
        # 메일 발송은 기본 OFF(운영 정책 supplier_inventory_mail) — 포털 알림만 남는다
        self.assertEqual(self.env["mail.mail"].search_count([("model", "=", "supplier.inventory"), ("res_id", "=", inv.id)]), mails_before)
        # 안 읽은 요청이 남아 있으면 다음 차감에서 중복 발송하지 않는다
        self._receive(po, 1)
        self.assertEqual(self.Notification.search_count([("partner_id", "=", self.vendor.id), ("notification_type", "=", "inventory_update")]), 1)
        # 협력사가 재고를 다시 신고하면 플래그가 풀린다
        inv.write({"quantity": 20})
        inv.invalidate_recordset()
        self.assertFalse(inv.needs_update)

    def _enable_inventory_mail(self):
        if "cams.ops.policy" in self.env:
            policy = self.env["cams.ops.policy"].sudo().search([("company_id", "=", self.company.id)], limit=1)
            vals = {"supplier_inventory_mail": True, "change_reason": "시험: 협력사 재고 메일 발송 확인"}
            policy.write(vals) if policy else self.env["cams.ops.policy"].sudo().create(dict(vals, company_id=self.company.id))
        else:
            self.env["ir.config_parameter"].sudo().set_param("supplier_portal_purchase.inventory_update_mail", "True")

    def test_update_mail_sent_only_when_enabled(self):
        """회사 정책(또는 매개변수)으로 켠 회사만 협력사에게 갱신 요청 메일을 보낸다."""
        self._enable_inventory_mail()
        inv = self._inventory(5)
        po = self._po(6)
        mails_before = self.env["mail.mail"].search_count([("model", "=", "supplier.inventory")])
        self._receive(po, 3)
        inv.invalidate_recordset()
        self.assertTrue(inv.needs_update)
        mails = self.env["mail.mail"].search([("model", "=", "supplier.inventory"), ("res_id", "=", inv.id)])
        self.assertEqual(len(mails), 1)
        self.assertEqual(self.env["mail.mail"].search_count([("model", "=", "supplier.inventory")]), mails_before + 1)
        self.assertIn(self.vendor.email, mails.email_to)

    def test_floor_at_zero_and_non_portal_vendor_untouched(self):
        inv = self._inventory(1)
        po = self._po(3)
        self._receive(po, 3)
        inv.invalidate_recordset()
        self.assertEqual(inv.quantity, 0)
        other = self._po(2, vendor=self.plain_vendor)
        picking = self._receive(other, 2)
        self.assertFalse(picking.move_ids.supplier_inventory_deducted, "포털 협력사가 아니면 차감 대상이 아니다")
        self.assertFalse(self.Inventory.search([("partner_id", "=", self.plain_vendor.id)]))

    def test_needs_update_search_filter(self):
        short = self._inventory(1)
        self._po(5)
        self.assertIn(short, self.Inventory.search([("needs_update", "=", True)]))
        self.assertNotIn(short, self.Inventory.search([("needs_update", "=", False)]))


@tagged("post_install", "-at_install")
class TestSupplierInventorySyncRoute(HttpCase):
    """협력사가 실제로 보는 경로(첫 화면·내 재고 관리)에 갱신 필요 배너와 요구량 열이 나오는지."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.token = "invs" + "0123456789abcdef" * 2
        cls.vendor = cls.env["res.partner"].create({
            "name": "INV-SYNC 라우트 협력사", "supplier_rank": 1, "is_supplier_portal": True,
            "supplier_portal_company_ids": [Command.set(cls.env.company.ids)], "supplier_portal_token": cls.token})
        cls.part = cls.env["product.product"].create({"name": "INV-SYNC 라우트 부품", "default_code": "INVSYNC-R", "type": "consu", "is_storable": True})
        cls.env["product.supplierinfo"].create({"partner_id": cls.vendor.id, "product_tmpl_id": cls.part.product_tmpl_id.id,
                                                "company_id": cls.env.company.id, "price": 100})
        cls.env["supplier.inventory"].create({"company_id": cls.env.company.id, "partner_id": cls.vendor.id,
                                              "product_id": cls.part.id, "quantity": 2})
        po = cls.env["purchase.order"].create({
            "partner_id": cls.vendor.id, "company_id": cls.env.company.id,
            "order_line": [Command.create({"name": cls.part.name, "product_id": cls.part.id, "product_qty": 7,
                                           "product_uom": cls.part.uom_id.id, "price_unit": 100})]})
        po.button_confirm()
        cls.env.flush_all()

    def test_dashboard_and_inventory_show_shortage(self):
        resp = self.url_open("/supplier/portal?token=%s" % self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("재고 갱신 필요", resp.text)
        self.assertIn("INV-SYNC 라우트 부품", resp.text)
        resp = self.url_open("/supplier/my-inventory?token=%s" % self.token)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("당사 미입고 요구량", resp.text)
        self.assertIn("갱신 필요 (부족 5)", resp.text)
        self.assertNotIn("Internal Server Error", resp.text)
