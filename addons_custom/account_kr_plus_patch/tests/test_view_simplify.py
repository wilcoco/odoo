from lxml import etree

from odoo.tests import TransactionCase, tagged

from ..item_backfill import backfill_legacy_item_names


@tagged("post_install", "-at_install")
class TestMoveFormHideFields(TransactionCase):
    """매입/매출처 청구서 화면 정리 — 숨김 뷰와 기 데이터 품목명 백필."""

    def _get_form_arch(self):
        view = self.env.ref("account.view_move_form")
        res = self.env["account.move"].get_view(view_id=view.id)
        return etree.fromstring(res["arch"])

    def test_unused_fields_are_hidden(self):
        """기타 정보 탭의 미사용 필드에 invisible=1 이 걸려 있다."""
        arch = self._get_form_arch()
        always_present = (
            "invoice_incoterm_id", "incoterm_location", "auto_post",
            "auto_post_until",
        )
        for fname in always_present:
            nodes = arch.xpath(
                "//page[@id='other_tab']//field[@name='%s']" % fname)
            self.assertTrue(nodes, "%s 노드가 폼에 없다" % fname)
            for node in nodes:
                self.assertEqual(node.get("invisible"), "1",
                                 "%s 이 숨겨지지 않았다" % fname)
        # 청구서 탭의 회계 포지션·확인 완료·결제 방법은 숨기고,
        # 분개(entry) 탭의 동명 필드는 남긴다
        for fname in ("fiscal_position_id", "checked",
                      "preferred_payment_method_line_id"):
            for node in arch.xpath(
                    "//group[@name='accounting_info_group']/field[@name='%s']" % fname):
                self.assertEqual(node.get("invisible"), "1", fname)
        for node in arch.xpath(
                "//page[@id='other_tab_entry']//field[@name='fiscal_position_id']"):
            self.assertNotEqual(node.get("invisible"), "1",
                                "분개 탭 회계 포지션까지 숨겨졌다")
        # 그룹/개발자모드 게이트가 있는 노드는 arch 에 남아 있을 때만 검사
        for fname in ("secured", "inalterable_hash"):
            for node in arch.xpath(
                    "//page[@id='other_tab']//field[@name='%s']" % fname):
                self.assertEqual(node.get("invisible"), "1", fname)
        for node in arch.xpath("//group[@name='utm_link']"):
            self.assertEqual(node.get("invisible"), "1", "마케팅 그룹")

    def test_backfill_without_column_is_noop(self):
        """수동 필드가 없는 DB(개발 등)에서는 백필이 조용히 건너뛴다."""
        if "x_escon_item_name" in self.env["account.move"]._fields:
            self.skipTest("이 DB 에는 수동 필드가 이미 있다")
        self.assertEqual(backfill_legacy_item_names(self.env), 0)

    def test_backfill_fills_empty_item_name_from_lines(self):
        """빈 x_escon_item_name 이 라인 데이터(kr_product_names)로 채워진다."""
        Move = self.env["account.move"]
        if "x_escon_item_name" not in Move._fields:
            model = self.env["ir.model"]._get("account.move")
            self.env["ir.model.fields"].create({
                "name": "x_escon_item_name",
                "field_description": "품목명(수동)",
                "model_id": model.id,
                "ttype": "char",
                "state": "manual",
            })
            Move = self.env["account.move"]
        partner = self.env["res.partner"].create({"name": "품목백필 거래처"})
        move = Move.create({
            "move_type": "in_invoice",
            "partner_id": partner.id,
            "invoice_date": "2026-08-31",
            "invoice_line_ids": [(0, 0, {
                "name": "캐노피 설치 공사",
                "quantity": 1,
                "price_unit": 100.0,
            })],
        })
        kept = Move.create({
            "move_type": "in_invoice",
            "partner_id": partner.id,
            "invoice_date": "2026-08-31",
            "x_escon_item_name": "이미 있는 품목명",
            "invoice_line_ids": [(0, 0, {
                "name": "다른 라인", "quantity": 1, "price_unit": 10.0,
            })],
        })
        self.assertFalse(move.x_escon_item_name)
        self.assertEqual(move.kr_product_names, "캐노피 설치 공사")
        self.env.flush_all()
        filled = backfill_legacy_item_names(self.env)
        self.assertGreaterEqual(filled, 1)
        (move + kept).invalidate_recordset(["x_escon_item_name"])
        self.assertEqual(move.x_escon_item_name, "캐노피 설치 공사",
                         "빈 품목명이 라인 데이터로 채워져야 한다")
        self.assertEqual(kept.x_escon_item_name, "이미 있는 품목명",
                         "이미 있는 값은 덮어쓰면 안 된다")
