from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestBlend(TransactionCase):
    """분쇄·배합일지 — SQ 사출 1_10 / 3_4.

    요청서 4항이 요구한 테스트 3종을 이 도메인에 맞춰 옮겼다.
      ① 정상 기록 생성      → 기준·분쇄·배합 한 바퀴
      ② 기한(적용일) 경과 판정 → 배합일 시점에 유효한 기준을 고르는가
      ③ 상하한 벗어난 값의 합부 → 재생재 비율 대 기준 상한
    여기에 허위기재 차단(판정 덮어쓰기·상태 직접 변경·완료 후 줄 삭제)을 더했다.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Standard = cls.env["iatf.blend.standard"]
        cls.Blend = cls.env["iatf.blend.log"]
        cls.Regrind = cls.env["iatf.regrind.log"]
        cls.today = fields.Date.context_today(cls.Standard)

        cls.part = cls.env["product.product"].create({"name": "TEST 사출품 A"})
        cls.resin = cls.env["product.product"].create({"name": "TEST 수지 PP"})
        cls.mb = cls.env["product.product"].create({"name": "TEST 마스터배치"})
        cls.machine = cls.env["iatf.equipment"].create({
            "name": "TEST 배합기 1호", "node_type": "equipment"})

    # ── 헬퍼 ──────────────────────────────────────────────────────────
    def _standard(self, **kw):
        vals = {"product_id": self.part.id, "max_regrind_ratio": 20.0,
                "effective_date": self.today - timedelta(days=30)}
        vals.update(kw)
        return self.Standard.create(vals)

    def _regrind(self, **kw):
        vals = {"regrind_date": self.today, "source_product_id": self.resin.id,
                "source_type": "sprue", "input_qty": 100.0, "output_qty": 90.0,
                "foreign_check": "ok"}
        vals.update(kw)
        return self.Regrind.create(vals)

    def _blend(self, virgin=80.0, regrind=20.0, additive=0.0, regrind_log=None, **kw):
        """투입 줄까지 갖춘 배합일지 하나."""
        lines = []
        if virgin:
            lines.append((0, 0, {"material_type": "virgin",
                                 "product_id": self.resin.id, "qty": virgin}))
        if regrind:
            src = regrind_log if regrind_log is not None else self._regrind()
            lines.append((0, 0, {"material_type": "regrind",
                                 "product_id": self.resin.id, "qty": regrind,
                                 "regrind_log_id": src.id}))
        if additive:
            lines.append((0, 0, {"material_type": "additive",
                                 "product_id": self.mb.id, "qty": additive}))
        vals = {"blend_date": self.today, "product_id": self.part.id,
                "equipment_id": self.machine.id, "line_ids": lines}
        vals.update(kw)
        return self.Blend.create(vals)

    # ── 1. 정상 기록 생성 ─────────────────────────────────────────────
    def test_standard_gets_number_and_survives(self):
        std = self._standard()
        self.assertTrue(std.name.startswith("BS-"), std.name)
        self.assertEqual(std.ratio_basis, "resin")

    def test_regrind_log_normal_flow(self):
        rg = self._regrind()
        self.assertTrue(rg.name.startswith("RG-"), rg.name)
        self.assertEqual(rg.state, "draft")
        self.assertAlmostEqual(rg.loss_qty, 10.0, places=3)
        self.assertAlmostEqual(rg.yield_ratio, 90.0, places=2)
        rg.action_done()
        self.assertEqual(rg.state, "done")

    def test_blend_log_normal_flow(self):
        self._standard()
        b = self._blend()
        self.assertTrue(b.name.startswith("BL-"), b.name)
        self.assertAlmostEqual(b.virgin_qty, 80.0, places=3)
        self.assertAlmostEqual(b.regrind_qty, 20.0, places=3)
        self.assertAlmostEqual(b.resin_qty, 100.0, places=3)
        self.assertAlmostEqual(b.regrind_ratio, 20.0, places=2)
        self.assertEqual(b.result, "ok")
        b.action_done()
        self.assertEqual(b.state, "done")

    def test_regrind_source_is_visible_from_the_regrind_log(self):
        """분쇄 → 배합 방향으로도 추적이 되어야 한다."""
        self._standard()
        rg = self._regrind()
        self._blend(regrind_log=rg, regrind=15.0)
        self.assertAlmostEqual(rg.used_qty, 15.0, places=3)

    # ── 2. 적용일(날짜) 판정 ──────────────────────────────────────────
    def test_standard_picked_by_blend_date(self):
        """배합일 시점에 유효한 기준을 고른다."""
        old = self._standard(max_regrind_ratio=10.0,
                             effective_date=self.today - timedelta(days=60))
        new = self._standard(max_regrind_ratio=30.0,
                             effective_date=self.today - timedelta(days=5))
        recent = self._blend()
        self.assertEqual(recent.standard_id, new)
        older = self._blend(blend_date=self.today - timedelta(days=30))
        self.assertEqual(older.standard_id, old)

    def test_future_standard_is_not_applied(self):
        """적용일이 아직 오지 않은 기준으로 과거를 판정하지 않는다."""
        self._standard(max_regrind_ratio=10.0,
                       effective_date=self.today - timedelta(days=60))
        self._standard(max_regrind_ratio=50.0,
                       effective_date=self.today + timedelta(days=7))
        b = self._blend()
        self.assertAlmostEqual(b.limit_ratio, 10.0, places=2)
        self.assertEqual(b.result, "ng", "미래 기준을 당겨 쓰면 합격이 된다")

    def test_other_company_standard_is_not_applied(self):
        """다른 법인의 상한으로 우리 배합을 판정하면 안 된다.

        이 모델에는 다중회사 레코드 규칙이 없어서, 회사를 걸러 주지 않으면
        search 가 남의 회사 기준을 그대로 집어 온다. 상한만 바뀌어도 초과 배합이
        합격으로 뒤집힌다.
        """
        other = self.env["res.company"].create({"name": "TEST 타사"})
        self._standard(max_regrind_ratio=50.0, company_id=other.id)
        b = self._blend()          # 20%
        self.assertFalse(b.standard_id, "타사 기준이 자사 배합 판정에 딸려 들어왔다")
        self.assertEqual(b.result, "pending",
                         "기준이 없으면 합격이 아니라 미판정으로 남아야 한다")

    def test_own_company_standard_beats_the_global_one(self):
        """회사가 지정된 기준이 전사 공통 기준보다 우선한다."""
        self._standard(max_regrind_ratio=50.0, company_id=False)
        self._standard(max_regrind_ratio=10.0, company_id=self.env.company.id)
        b = self._blend()          # 20%
        self.assertAlmostEqual(b.limit_ratio, 10.0, places=2)
        self.assertEqual(b.result, "ng")

    def test_limit_is_snapshotted_against_later_edits(self):
        """기준을 나중에 완화해도 과거 판정이 따라 움직이면 안 된다."""
        std = self._standard(max_regrind_ratio=10.0)
        b = self._blend()          # 20% → 초과
        self.assertEqual(b.result, "ng")
        std.max_regrind_ratio = 90.0
        b.invalidate_recordset()
        self.assertAlmostEqual(b.limit_ratio, 10.0, places=2,
                               msg="기준 상한이 소급 변경됐다")
        self.assertEqual(b.result, "ng", "과거 초과 배합이 소급 합격됐다")

    def test_no_standard_leaves_judgement_pending(self):
        b = self._blend()
        self.assertFalse(b.standard_id)
        self.assertEqual(b.result, "pending")

    def test_future_dates_rejected(self):
        self._standard()
        with self.assertRaises(ValidationError):
            self._blend(blend_date=self.today + timedelta(days=1))
        with self.assertRaises(ValidationError):
            self._regrind(regrind_date=self.today + timedelta(days=1))

    # ── 3. 상한 대비 합부 판정 ────────────────────────────────────────
    def test_ratio_below_limit_is_ok(self):
        self._standard(max_regrind_ratio=20.0)
        self.assertEqual(self._blend(virgin=90.0, regrind=10.0).result, "ok")

    def test_ratio_exactly_at_limit_is_ok(self):
        """상한과 같은 값은 초과가 아니다. 경계에서 갈리므로 못 박아 둔다."""
        self._standard(max_regrind_ratio=20.0)
        b = self._blend(virgin=80.0, regrind=20.0)
        self.assertAlmostEqual(b.regrind_ratio, 20.0, places=2)
        self.assertEqual(b.result, "ok")

    def test_ratio_just_above_limit_is_ng(self):
        self._standard(max_regrind_ratio=20.0)
        b = self._blend(virgin=79.0, regrind=21.0)
        self.assertAlmostEqual(b.regrind_ratio, 21.0, places=2)
        self.assertEqual(b.result, "ng")

    def test_additive_limit_is_also_checked(self):
        self._standard(max_regrind_ratio=50.0, max_additive_ratio=3.0)
        ok = self._blend(virgin=80.0, regrind=20.0, additive=3.0)
        self.assertAlmostEqual(ok.additive_ratio, 100.0 * 3.0 / 103.0, places=2)
        self.assertEqual(ok.result, "ok")
        ng = self._blend(virgin=80.0, regrind=20.0, additive=10.0)
        self.assertEqual(ng.result, "ng")

    def test_ratio_basis_changes_the_denominator(self):
        """분모를 총 투입량으로 잡으면 같은 투입도 비율이 달라진다.
        회사가 고르게 둔 값이므로 두 경로 다 확인한다."""
        self._standard(max_regrind_ratio=20.0, ratio_basis="total")
        b = self._blend(virgin=80.0, regrind=20.0, additive=20.0)
        self.assertAlmostEqual(b.regrind_ratio, 100.0 * 20.0 / 120.0, places=2)
        self.assertEqual(b.result, "ok")

    def test_ratio_recomputes_when_a_line_changes(self):
        self._standard(max_regrind_ratio=20.0)
        b = self._blend(virgin=90.0, regrind=10.0)
        self.assertEqual(b.result, "ok")
        b.line_ids.filtered(lambda l: l.material_type == "regrind").qty = 40.0
        self.assertAlmostEqual(b.regrind_ratio, 100.0 * 40.0 / 130.0, places=2)
        self.assertEqual(b.result, "ng")

    def test_regrind_output_cannot_exceed_input(self):
        """산출이 투입보다 많으면 재생재가 허공에서 생긴다."""
        with self.assertRaises(ValidationError):
            self._regrind(input_qty=50.0, output_qty=60.0)

    def test_line_qty_must_be_positive(self):
        self._standard()
        with self.assertRaises(ValidationError):
            self._blend(virgin=0.0, regrind=0.0, additive=0.0, line_ids=[
                (0, 0, {"material_type": "virgin", "product_id": self.resin.id,
                        "qty": 0.0})])

    # ── 4. 허위기재·우회 차단 ─────────────────────────────────────────
    def test_result_cannot_be_overwritten(self):
        """기준을 넘긴 배합에 '기준 이내'를 적어 넣는 경로가 곧 허위기재다."""
        self._standard(max_regrind_ratio=10.0)
        b = self._blend()
        self.assertEqual(b.result, "ng")
        with self.assertRaises(ValidationError):
            b.write({"result": "ok"})

    def test_done_requires_lines(self):
        self._standard()
        b = self.Blend.create({"blend_date": self.today,
                               "product_id": self.part.id})
        with self.assertRaises(UserError):
            b.action_done()

    def test_done_requires_regrind_source(self):
        """출처 없는 재생재는 혼합일지가 있어도 추적이 끊긴다."""
        self._standard()
        b = self.Blend.create({
            "blend_date": self.today, "product_id": self.part.id,
            "line_ids": [
                (0, 0, {"material_type": "virgin", "product_id": self.resin.id,
                        "qty": 80.0}),
                (0, 0, {"material_type": "regrind", "product_id": self.resin.id,
                        "qty": 20.0}),
            ]})
        with self.assertRaises(UserError):
            b.action_done()
        b.line_ids.filtered(lambda l: l.material_type == "regrind").regrind_log_id = \
            self._regrind().id
        b.action_done()
        self.assertEqual(b.state, "done")

    def test_ng_blend_needs_an_action_before_done(self):
        self._standard(max_regrind_ratio=10.0)
        b = self._blend()
        self.assertEqual(b.result, "ng")
        with self.assertRaises(UserError):
            b.action_done()
        b.ng_action = "해당 LOT 격리 후 물성 재확인"
        b.action_done()
        self.assertEqual(b.state, "done")

    def test_state_write_cannot_bypass_done_guard(self):
        """버튼을 거치지 않는 경로(임포트·API)도 같은 규칙에 걸려야 한다."""
        self._standard()
        b = self.Blend.create({"blend_date": self.today,
                               "product_id": self.part.id})
        with self.assertRaises(ValidationError):
            b.write({"state": "done"})

    def test_completed_blend_cannot_be_gutted(self):
        """완료 뒤 줄을 지워 내용만 비우는 경로."""
        self._standard()
        b = self._blend()
        b.action_done()
        with self.assertRaises(ValidationError):
            b.line_ids.unlink()

    def test_regrind_source_cannot_be_hung_on_virgin_line(self):
        """신재 줄에 분쇄일지를 달면 재생재를 신재로 계상한 셈이 된다."""
        self._standard()
        rg = self._regrind()
        with self.assertRaises(ValidationError):
            self.Blend.create({
                "blend_date": self.today, "product_id": self.part.id,
                "line_ids": [(0, 0, {"material_type": "virgin",
                                     "product_id": self.resin.id, "qty": 80.0,
                                     "regrind_log_id": rg.id})]})

    def test_regrind_done_requires_foreign_check(self):
        rg = self._regrind(foreign_check=False)
        with self.assertRaises(UserError):
            rg.action_done()
        with self.assertRaises(ValidationError):
            rg.write({"state": "done"})
        rg.foreign_check = "ng"
        with self.assertRaises(UserError):
            rg.action_done()
        rg.foreign_action = "해당 배치 폐기"
        rg.action_done()
        self.assertEqual(rg.state, "done")

    def test_used_regrind_log_cannot_be_deleted(self):
        """배합에 쓰인 분쇄일지를 지우면 그 배합의 출처가 사라진다."""
        self._standard()
        rg = self._regrind()
        self._blend(regrind_log=rg)
        with self.assertRaises(Exception):
            rg.unlink()

    def test_approval_flag_needs_evidence(self):
        with self.assertRaises(ValidationError):
            self._standard(customer_approved=True)
        std = self._standard(customer_approved=True, approval_ref="APPR-001")
        self.assertTrue(std.customer_approved)

    def test_no_demo_records_shipped(self):
        """데모·샘플 실적을 넣지 않았다는 것을 테스트로 못 박는다."""
        for model in ("iatf.blend.standard", "iatf.blend.log", "iatf.regrind.log"):
            self.assertEqual(
                self.env["ir.model.data"].search_count([("model", "=", model)]), 0,
                "%s 에 데이터 파일로 실린 레코드가 있다" % model)
