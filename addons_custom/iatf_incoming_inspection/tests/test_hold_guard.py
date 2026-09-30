from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from .hold_release_fixture import make_policy, approve_and_release
from .quality_basis import QualityBasisMixin


@tagged("post_install", "-at_install")
class TestHoldGuard(QualityBasisMixin, TransactionCase):
    """품질 보류 로트 투입 차단 — 확정 시점 + 확정 후 lot 지정(실소비) 경로."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hold_policy, cls.hold_quality, cls.hold_production = make_policy(cls.env, 'guard')
        cls.raw = cls.env["product.product"].create({
            "name": "T-수지", "is_storable": True, "tracking": "lot"})
        # [아스트라 20260911-18 #5] 선행 품질게이트가 깔린 합본에서는 모든 MO 가
        # 승인 관리계획·추적 LOT·검사를 요구한다. 이 시험의 목적(보류 원재료 소비
        # 차단)을 유지하면서 **정상 업무 API 로** 그 기준을 갖춘다.
        # 게이트가 없는 환경에서는 아무것도 하지 않는다.
        cls.fin = cls.env["product.product"].create({
            "name": "T-완제품", "is_storable": True, "tracking": "lot"})
        cls.fin_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.fin.product_tmpl_id.id, "product_qty": 1,
            "type": "normal",
            "bom_line_ids": [(0, 0, {"product_id": cls.raw.id, "product_qty": 1})]})
        cls.mo = cls.env["mrp.production"].create({
            "product_id": cls.fin.id, "product_qty": 1,
            "bom_id": cls.fin_bom.id,
            "lot_producing_id": cls.env["stock.lot"].create({
                "name": "T-FIN-001", "product_id": cls.fin.id,
                "company_id": cls.env.company.id}).id,
            "move_raw_ids": [(0, 0, {
                "product_id": cls.raw.id, "product_uom_qty": 1,
                "product_uom": cls.raw.uom_id.id,
                "location_id": cls.env.ref("stock.stock_location_stock").id,
                "location_dest_id": cls.env.ref("stock.stock_location_stock").id,
            })]})
        cls._setup_quality_actors(cls.env.company)
        cls.held = cls.env["stock.lot"].create({
            "name": "HOLD-T-001", "product_id": cls.raw.id,
            "company_id": cls.env.company.id,
            "quality_hold": True, "hold_reason": "IQC 대기"})

    def test_consume_blocked_after_confirm(self):
        """확정 후 lot 지정 → 실소비 시점 차단 (기존 확정 시점만 검사하던 구멍 보강).

        ⚠ 막히는 **사유**를 구분한다. 품질 기준 미설정으로 막히면 이 시험이 보려던
        「보류 원재료 차단」을 확인한 것이 아니다. 그래서 기준을 먼저 갖춘다."""
        self.mo.action_confirm()
        self._ensure_quality_basis(self.mo)
        move = self.mo.move_raw_ids
        self.env["stock.move.line"].create({
            "move_id": move.id, "product_id": self.raw.id, "lot_id": self.held.id,
            "quantity": 1, "location_id": move.location_id.id,
            "location_dest_id": move.location_dest_id.id})
        with self.assertRaises(UserError) as caught:
            move._action_done()
        # **보류 때문에** 막힌 것인지 확인한다 (기준 미설정이면 다른 문제다)
        self.assertIn("품질 보류", str(caught.exception),
                      "보류가 아니라 다른 사유로 막혔다: %s" % caught.exception)
        # 보류 해제 후엔 가드 통과 (Odoo18: picked 지정 후 완료)
        approve_and_release(self.env, self.held, self.hold_quality, self.hold_production)
        move.picked = True
        move._action_done()
        self.assertEqual(move.state, "done")
