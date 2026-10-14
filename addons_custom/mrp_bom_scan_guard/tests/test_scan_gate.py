"""부품 이종검사 — 판정과 **실제 차단**.

배정 `20260911-02` 3·4항. 기존 가드는 결과를 적어 주기만 하고 아무것도 막지 않았다.
여기서는 **막히는지**를 본다.

**이 시험이 보증하지 않는 것**: 품질 합격 기준값과 CP/PFMEA 선행·초중종 검사 차단.
그쪽은 `iatf_quality_precedence` 소유라 중복 구현하지 않았다.
"""
from datetime import timedelta

from odoo import Command, fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged

from .quality_basis import QualityBasisMixin


@tagged("post_install", "-at_install")
class TestScanGate(QualityBasisMixin, TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.unit = cls.env.ref("uom.product_uom_unit")

        def product(name, tracking="none"):
            return cls.env["product.product"].create({
                "name": name, "is_storable": True, "type": "consu",
                "tracking": tracking, "uom_id": cls.unit.id, "uom_po_id": cls.unit.id,
                "default_code": name,
            })

        # 완제품은 **LOT 추적**이다. 조립 완제품은 차체 단위로 LOT 을 매기고,
        # 선행 품질게이트도 「생산 품질 범위를 추적할 LOT 관리 기준」을 요구한다.
        cls.finished = product("SG-완제품", tracking="lot")
        cls.part_ok = product("SG-정상부품", tracking="lot")
        cls.part_other_bom = product("SG-타BOM부품")
        cls.part_untracked = product("SG-무추적부품")

        # 가드는 **작업지시 단위**라 라우팅이 있어야 한다.
        cls.workcenter = cls.env["mrp.workcenter"].create({
            "name": "SG-조립", "company_id": cls.company.id})
        cls.bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.finished.product_tmpl_id.id,
            "product_qty": 1.0, "type": "normal",
            "operation_ids": [Command.create({
                "name": "SG-조립공정", "workcenter_id": cls.workcenter.id})],
            "bom_line_ids": [
                Command.create({"product_id": cls.part_ok.id, "product_qty": 1.0}),
                Command.create({"product_id": cls.part_untracked.id, "product_qty": 1.0}),
            ],
        })
        cls.operation = cls.bom.operation_ids[:1]
        cls.bom.bom_line_ids.operation_id = cls.operation.id
        # 다른 차종/BOM — 오품 스캔의 상대편
        cls.other_finished = product("SG-타차종완제품")
        cls.other_bom = cls.env["mrp.bom"].create({
            "product_tmpl_id": cls.other_finished.product_tmpl_id.id,
            "product_qty": 1.0, "type": "normal",
            "bom_line_ids": [
                Command.create({"product_id": cls.part_other_bom.id, "product_qty": 1.0})],
        })
        if "alc" in cls.env["mrp.bom"]._fields:
            cls.bom.alc = "ALC-A"
            cls.other_bom.alc = "ALC-B"
        cls._setup_quality_actors(cls.company)

    def _mo(self):
        values = {
            "product_id": self.finished.id, "product_qty": 1.0,
            "bom_id": self.bom.id, "product_uom_id": self.unit.id,
        }
        if self.finished.tracking != "none":
            values["lot_producing_id"] = self.env["stock.lot"].create({
                "name": "SG-완제품-LOT-%s" % self.env["mrp.production"].search_count([]),
                "product_id": self.finished.id,
                "company_id": self.company.id}).id
        mo = self.env["mrp.production"].create(values)
        mo.action_confirm()
        # 합본에서는 선행 품질게이트가 `button_finish`/`button_mark_done` 을 먼저
        # 막는다. 그러면 **내가 시험하려는 이종검사 가드에 도달하지 못한다**
        # (실제로 합본 실행에서 내 단언 문구가 품질 문구로 바뀌어 실패했다).
        # 정상 경로 기준정보를 갖춰 원래 가드까지 가게 한다.
        self._ensure_quality_basis(mo)
        return mo

    def _wizard(self, mo):
        workorder = mo.workorder_ids[:1]
        if not workorder:
            # 라우팅이 없으면 작업지시가 없다 — 가드는 작업지시 단위다.
            self.skipTest("이 기준정보에는 작업지시가 없다")
        return self.env["mrp.bom.scan.guard.wizard"].create({
            "workorder_id": workorder.id}), workorder

    def _lot(self, product, name):
        return self.env["stock.lot"].create({
            "name": name, "product_id": product.id, "company_id": self.company.id})

    # ── ① 정상 부품은 통과하고 증빙이 남는다 ──
    def test_a_correct_part_passes_and_is_recorded(self):
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        lot = self._lot(self.part_ok, "SG-LOT-정상")
        wiz.scan_value = lot.name
        self.assertTrue(wiz.action_confirm_scan())

        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id)], limit=1)
        self.assertEqual(log.result_state, "ok")
        self.assertEqual(log.lot_id, lot)
        self.assertEqual(log.bom_id, self.bom)
        self.assertFalse(log.blocking)

    # ── ② 다른 차종 부품은 '다른 차종' 으로 차단된다 ──
    def test_a_part_from_another_vehicle_is_blocked_as_such(self):
        """`wrong_vehicle` 과 `wrong_bom_revision` 을 **구분해서** 건다.
        둘 중 아무거나 통과시키면 한쪽 분기는 영영 시험되지 않는다."""
        if "alc" not in self.env["mrp.bom"]._fields:
            self.skipTest("이 DB 에 차종(ALC) 필드가 없다")
        self.assertEqual(self.bom.alc, "ALC-A")
        self.assertEqual(self.other_bom.alc, "ALC-B")

        mo = self._mo()
        wiz, _wo = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        result = wiz.action_confirm_scan()
        self.assertEqual(result.get("params", {}).get("type"), "danger",
                         "거부를 화면에 알리지 않았다")
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("matched_product_id", "=", self.part_other_bom.id)], limit=1)
        self.assertEqual(log.result_state, "wrong_vehicle",
                         "차종이 다른데 차종 사유로 잡지 않았다")
        self.assertTrue(log.blocking, "차단인데 차단으로 기록되지 않았다")
        self.assertEqual(log.vehicle_code, "ALC-A", "이 오더의 차종을 증빙에 남기지 않았다")

    # ── ②-b 차종이 같으면 '다른 BOM' 으로 차단된다 ──
    def test_a_part_from_another_bom_of_the_same_vehicle_is_blocked(self):
        """차종이 같으면 차종 사유가 아니라 **BOM 사유**로 잡혀야 한다."""
        same_vehicle_part = self.env["product.product"].create({
            "name": "SG-같은차종_다른BOM부품", "is_storable": True, "type": "consu",
            "uom_id": self.unit.id, "uom_po_id": self.unit.id,
            "default_code": "SG-같은차종_다른BOM부품"})
        other = self.env["product.product"].create({
            "name": "SG-같은차종완제품", "is_storable": True, "type": "consu",
            "uom_id": self.unit.id, "uom_po_id": self.unit.id})
        same_vehicle_bom = self.env["mrp.bom"].create({
            "product_tmpl_id": other.product_tmpl_id.id, "product_qty": 1.0,
            "type": "normal",
            "bom_line_ids": [Command.create(
                {"product_id": same_vehicle_part.id, "product_qty": 1.0})]})
        if "alc" in self.env["mrp.bom"]._fields:
            same_vehicle_bom.alc = self.bom.alc      # 같은 차종

        mo = self._mo()
        wiz, _wo = self._wizard(mo)
        wiz.scan_value = same_vehicle_part.default_code
        wiz.action_confirm_scan()
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("matched_product_id", "=", same_vehicle_part.id)], limit=1)
        self.assertEqual(log.result_state, "wrong_bom_revision",
                         "같은 차종인데 차종 사유로 잡았다")

    # ── ②-c BOM 개정 차수가 증빙에 남는다 ──
    def test_the_applied_bom_revision_is_recorded(self):
        """배정 3항의 「다른 BOM/차종 **개정** 기준」 중 **개정** 부분.

        개정은 `mrp.bom.bom_version_id` → `escon.bom.version` 에서 읽는다.
        그 필드가 없는 환경도 있어 코드가 막아 두었지만, **있는 환경에서 실제로
        읽히는지**는 따로 확인해야 한다."""
        Bom = self.env["mrp.bom"]
        if "bom_version_id" not in Bom._fields:
            self.skipTest("이 DB 에 BOM 개정(escon_bom_util) 이 없다")
        vals = {"name": "SG-개정-v1"}
        Version = self.env["escon.bom.version"]
        if "management_number_id" in Version._fields:
            # [R145] 운영 BOM PLM(escon_bom_util 18.0.2.5.0): Batch(개정)에는 관리번호가 필요하다.
            dept = self.env["hr.department"].create({"name": "T-스캔관문팀"})
            number = self.env["escon.bom.management.number"].create({"name": "TEST-SCAN-GATE", "department_id": dept.id})
            vals["management_number_id"] = number.id
        version = Version.create(vals)
        self.bom.bom_version_id = version.id

        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        lot = self._lot(self.part_ok, "SG-LOT-개정")
        wiz.scan_value = lot.name
        wiz.action_confirm_scan()

        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id), ("lot_id", "=", lot.id)], limit=1)
        self.assertEqual(log.result_state, "ok")
        self.assertTrue(log.bom_revision, "적용 BOM 개정이 증빙에 남지 않았다")
        self.assertIn("SG-개정-v1", log.bom_revision)

    # ── ③ 알 수 없는 스캔값은 차단된다 ──
    def test_an_unknown_scan_value_is_blocked(self):
        mo = self._mo()
        wiz, _wo = self._wizard(mo)
        wiz.scan_value = "SG-존재하지않는값"
        wiz.action_confirm_scan()
        self.assertEqual(wiz.result_state, "unknown_lot")

    # ── ④ 품질 보류 LOT 은 차단된다 ──
    def test_a_quality_held_lot_is_blocked(self):
        if "quality_hold" not in self.env["stock.lot"]._fields:
            self.skipTest("이 DB 에 품질 보류 필드가 없다")
        mo = self._mo()
        wiz, _wo = self._wizard(mo)
        lot = self._lot(self.part_ok, "SG-LOT-보류")
        lot.sudo().quality_hold = True
        wiz.scan_value = lot.name
        result = wiz.action_confirm_scan()
        self.assertEqual(wiz.result_state, "quality_hold")
        self.assertIn("품질 보류", result["params"]["message"])

    # ── ⑤ 같은 LOT 재투입은 차단된다 (2초 debounce 가 아니라) ──
    def test_the_same_lot_cannot_be_consumed_twice(self):
        mo = self._mo()
        wiz, _wo = self._wizard(mo)
        lot = self._lot(self.part_ok, "SG-LOT-중복")
        wiz.scan_value = lot.name
        wiz.action_confirm_scan()

        wiz.scan_value = lot.name
        wiz.action_confirm_scan()
        self.assertEqual(wiz.result_state, "duplicate_scan")

    # ── ⑥ LOT 관리 품목인데 LOT 을 못 읽으면 통과시키지 않는다 ──
    def test_a_tracked_product_without_a_lot_is_blocked(self):
        mo = self._mo()
        wiz, _wo = self._wizard(mo)
        wiz.scan_value = self.part_ok.default_code      # 품번만, LOT 아님
        wiz.action_confirm_scan()
        self.assertEqual(wiz.result_state, "unknown_lot")

    # ── ⑦ 미해소 차단이 남으면 작업을 완료하지 못한다 ──
    def test_an_unresolved_block_stops_the_workorder(self):
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        wiz.action_confirm_scan()

        with self.assertRaises(UserError) as caught:
            workorder.button_finish()
        self.assertIn("이종검사 차단", str(caught.exception))

    # ── ⑧ 사유 있는 해소 뒤에만 진행된다 ──
    def test_it_proceeds_only_after_a_reasoned_resolution(self):
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        wiz.action_confirm_scan()
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id), ("blocking", "=", True)], limit=1)

        # 사유 없이 풀 수 없다
        with self.assertRaises(UserError):
            log.action_resolve()

        log.action_resolve(reason="정상 부품으로 재스캔, 반장 확인")
        self.assertTrue(log.resolved)
        self.assertEqual(log.resolved_by, self.env.user)
        workorder._assert_scan_guard_clear()     # 더 이상 막지 않는다

    # ── ⑧-2 **일반 작업자는 사유를 적어도 차단을 풀 수 없다** ──
    def test_an_ordinary_worker_cannot_resolve_a_block(self):
        """[아스트라 20260912 04:45] 「`action_resolve` 에서 **역할 검사 없이 sudo
        쓰기**하는지 검토 요청합니다. … **일반작업자 경보해제 시도**/타회사 로그
        접근 거부를 재현하고 관리자 정정 사유·재스캔 정상 절차 유지하십시오.」

        원장 ACL 은 일반 사용자에게 **읽기만** 줬는데 이 메서드가 `sudo()` 로
        그것을 넘고 있었습니다. **사유만 적으면 아무나 풀 수 있었습니다.**
        """
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        wiz.action_confirm_scan()
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id), ("blocking", "=", True)], limit=1)

        worker = new_test_user(
            self.env["res.users"].with_context(
                no_reset_password=True, mail_create_nosubscribe=True,
                mail_notrack=True).env,
            login="scan-ordinary-worker",
            groups="base.group_user,mrp.group_mrp_user")
        self.assertFalse(worker.has_group("mrp.group_mrp_manager"))

        with self.assertRaises(UserError) as caught:
            log.with_user(worker).action_resolve(reason="그냥 풀겠습니다")
        self.assertIn("생산관리자", str(caught.exception))
        log.invalidate_recordset()
        self.assertFalse(log.resolved, "일반 작업자가 차단을 풀었다")
        # **차단은 그대로 서 있다**
        with self.assertRaises(UserError):
            workorder._assert_scan_guard_clear()

    # ── ⑧-3 **다른 회사의 기록은 관리자라도 풀 수 없다** ──
    def test_a_manager_cannot_resolve_another_companys_block(self):
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        wiz.action_confirm_scan()
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id), ("blocking", "=", True)], limit=1)

        other = self.env["res.company"].create({"name": "스캔-타회사"})
        stranger = new_test_user(
            self.env["res.users"].with_context(
                no_reset_password=True, mail_create_nosubscribe=True,
                mail_notrack=True).env,
            login="scan-other-company-manager",
            groups="base.group_user,mrp.group_mrp_user,mrp.group_mrp_manager",
            company_id=other.id, company_ids=[Command.set(other.ids)])

        with self.assertRaises(UserError) as caught:
            log.with_user(stranger).action_resolve(reason="타사 관리자 해소 시도")
        self.assertIn("허용된 회사", str(caught.exception))
        log.invalidate_recordset()
        self.assertFalse(log.resolved, "다른 회사 관리자가 차단을 풀었다")

    # ── ⑨ 차단 이력은 지워지지 않는다 ──
    def test_a_blocked_scan_is_always_recorded(self):
        """처음 구현은 차단 시 UserError 를 올렸다. Odoo 에서 예외가 서버 메서드 밖으로
        나가면 그 트랜잭션이 통째로 롤백되므로 **방금 남긴 차단 증빙까지 사라진다.**
        이 시험이 그것을 잡았다. 차단은 게이트(`button_finish`)가 하고, 여기서는
        사실을 남긴다."""
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        before = self.env["mrp.bom.scan.guard.log"].search_count(
            [("workorder_id", "=", workorder.id)])
        wiz.scan_value = "SG-존재하지않는값"
        wiz.action_confirm_scan()
        after = self.env["mrp.bom.scan.guard.log"].search_count(
            [("workorder_id", "=", workorder.id)])
        self.assertEqual(after, before + 1, "차단된 스캔이 증빙으로 남지 않았다")

    # ── ⑩ 차단이 얼마나 서 있었는지 잰다 ──
    def test_a_block_records_how_long_it_stood(self):
        """[운영기준 20260911-06 5항] 차단 자체는 옳지만, 얼마나 오래 서 있었는지
        모르면 BR 수신 후 2시간 납기를 지킬 수 없다."""
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        wiz.action_confirm_scan()
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id), ("blocking", "=", True)], limit=1)

        self.assertTrue(log, "차단이 기록되지 않았다")
        self.assertGreaterEqual(log.blocked_minutes, 0.0)
        self.assertFalse(log.overdue, "방금 생긴 차단이 경보 한도 초과로 잡혔다")

        # 한도를 넘긴 것처럼 과거로 밀면 납기 초과로 잡혀야 한다.
        past = fields.Datetime.now() - timedelta(minutes=200)
        self.env.cr.execute(
            "UPDATE mrp_bom_scan_guard_log SET create_date = %s WHERE id = %s",
            [past, log.id])
        log.invalidate_recordset()
        self.assertGreater(log.blocked_minutes, 120.0)
        self.assertTrue(log.overdue, "경보 한도를 넘겼는데 표시되지 않았다")

    # ── ⑪ 경보 한도 0 이면 판정하지 않는다 (명시적 끄기) ──
    def test_a_zero_deadline_turns_the_verdict_off(self):
        """0 은 '설정 안 함' 이 아니라 **끄기**다. 기본값으로 되살리지 않는다."""
        self.env.company.scan_block_alert_minutes = 0.0
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        wiz.action_confirm_scan()
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id), ("blocking", "=", True)], limit=1)
        past = fields.Datetime.now() - timedelta(minutes=500)
        self.env.cr.execute(
            "UPDATE mrp_bom_scan_guard_log SET create_date = %s WHERE id = %s",
            [past, log.id])
        log.invalidate_recordset()
        self.assertGreater(log.blocked_minutes, 120.0)
        self.assertFalse(log.overdue, "경보를 껐는데 초과로 잡았다")

    # ── ⑫ 경보 한도를 넘긴 차단은 제조오더에 경보로 남는다 ──
    def test_an_overdue_block_is_alerted_on_the_order(self):
        mo = self._mo()
        wiz, workorder = self._wizard(mo)
        wiz.scan_value = self.part_other_bom.default_code
        wiz.action_confirm_scan()
        log = self.env["mrp.bom.scan.guard.log"].search(
            [("workorder_id", "=", workorder.id), ("blocking", "=", True)], limit=1)
        past = fields.Datetime.now() - timedelta(minutes=200)
        self.env.cr.execute(
            "UPDATE mrp_bom_scan_guard_log SET create_date = %s WHERE id = %s",
            [past, log.id])
        log.invalidate_recordset()

        # 게이트 메시지에는 경과·초과가 보인다
        with self.assertRaises(UserError) as caught:
            workorder.button_finish()
        self.assertIn("경보 한도 초과", str(caught.exception))

        # 경보는 게이트가 아니라 주기 작업이 남긴다 — 게이트는 예외를 올리는 자리라
        # 거기서 남긴 것은 롤백된다(시험이 실제로 그것을 잡았다).
        before = len(mo.message_ids)
        posted = self.env["mrp.bom.scan.guard.log"]._cron_alert_overdue_scan_blocks()
        self.assertEqual(posted, 1)
        mo.invalidate_recordset()
        self.assertGreater(len(mo.message_ids), before, "경보가 남지 않았다")

        # 같은 차단으로 되풀이 경보하지 않는다
        again = self.env["mrp.bom.scan.guard.log"]._cron_alert_overdue_scan_blocks()
        self.assertEqual(again, 0, "같은 차단으로 또 경보했다")
