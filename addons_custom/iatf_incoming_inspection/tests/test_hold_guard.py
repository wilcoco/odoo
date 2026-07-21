from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestHoldGuard(TransactionCase):
    """품질 보류 로트 투입 차단 — 확정 시점 + 확정 후 lot 지정(실소비) 경로."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.raw = cls.env["product.product"].create({
            "name": "T-수지", "is_storable": True, "tracking": "lot"})
        cls.fin = cls.env["product.product"].create({"name": "T-완제품", "is_storable": True})
        cls.mo = cls.env["mrp.production"].create({
            "product_id": cls.fin.id, "product_qty": 1,
            "move_raw_ids": [(0, 0, {
                "product_id": cls.raw.id, "product_uom_qty": 1,
                "product_uom": cls.raw.uom_id.id,
                "location_id": cls.env.ref("stock.stock_location_stock").id,
                "location_dest_id": cls.env.ref("stock.stock_location_stock").id,
            })]})
        cls.held = cls.env["stock.lot"].create({
            "name": "HOLD-T-001", "product_id": cls.raw.id,
            "company_id": cls.env.company.id,
            "quality_hold": True, "hold_reason": "IQC 대기"})

    def test_consume_blocked_after_confirm(self):
        """확정 후 lot 지정 → 실소비 시점 차단 (기존 확정 시점만 검사하던 구멍 보강)."""
        self.mo.action_confirm()
        move = self.mo.move_raw_ids
        self.env["stock.move.line"].create({
            "move_id": move.id, "product_id": self.raw.id, "lot_id": self.held.id,
            "quantity": 1, "location_id": move.location_id.id,
            "location_dest_id": move.location_dest_id.id})
        with self.assertRaises(UserError):
            move._action_done()
        # 보류 해제 후엔 가드 통과 (Odoo18: picked 지정 후 완료)
        self.held.quality_hold = False
        move.picked = True
        move._action_done()
        self.assertEqual(move.state, "done")
