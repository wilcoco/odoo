from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoldTryout(TransactionCase):
    """시사출(T/O) 보고서 (SQ 4_5).

    ① 정상 기록 생성 — 번호·차수 채번, 금형 연결
    ② 기한/누락 판정 — 사용 중인데 합격 T/O 가 없는 금형 적발
    ③ 상·하한 벗어난 값의 합부 판정 — 수량이 시사출 타수를 넘으면 저장 거부
    """

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({
            "name": "T-이관금형", "mold_type": "injection",
        })
        self.Tryout = self.env["iatf.mold.tryout"]

    def _tryout(self, **vals):
        base = {"mold_id": self.mold.id, "reason": "transfer"}
        base.update(vals)
        return self.Tryout.create(base)

    # ───────── ① 정상 기록 생성 ─────────

    def test_create_numbers_and_links(self):
        to1 = self._tryout(shot_count=50, ok_qty=45, ng_qty=5, conclusion="pass")
        self.assertNotEqual(to1.name, "New", "시퀀스로 번호가 붙는다")
        self.assertTrue(to1.name.startswith("TO-"))
        self.assertEqual(to1.tryout_no, 1, "첫 시사출은 1차")
        self.assertEqual(to1.state, "draft")
        self.assertAlmostEqual(to1.defect_rate, 10.0, places=2)
        self.assertIn(to1, self.mold.tryout_ids)
        self.assertEqual(self.mold.tryout_count, 1)

        to2 = self._tryout(reason="repair")
        self.assertEqual(to2.tryout_no, 2, "같은 금형의 다음 차수는 자동 증가")

        other = self.env["iatf.mold"].create({"name": "T-다른금형"})
        to3 = self.Tryout.create({"mold_id": other.id, "reason": "new"})
        self.assertEqual(to3.tryout_no, 1, "차수는 금형별로 센다")

    def test_last_tryout_date_and_done_requires_conclusion(self):
        today = fields.Date.context_today(self.mold)
        old = self._tryout(tryout_date=today - relativedelta(days=10))
        new = self._tryout(tryout_date=today)
        self.mold.invalidate_recordset()
        self.assertEqual(self.mold.last_tryout_date, today)

        with self.assertRaises(UserError, msg="판정 없이 완료 불가"):
            old.action_done()
        old.conclusion = "hold"
        old.action_done()
        self.assertEqual(old.state, "done")
        new.unlink()

    def test_mold_delete_blocked_while_evidence_exists(self):
        """증빙이 달린 금형은 지워지지 않는다 — 보고서가 조용히 사라지면 안 된다."""
        to = self._tryout(conclusion="pass")
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.mold.unlink()
        to.unlink()
        self.mold.unlink()  # 증빙이 없으면 정상 삭제

    def test_duplicate_tryout_no_rejected(self):
        """같은 금형 같은 차수는 둘일 수 없다 — 증빙 번호가 겹치면 설명이 안 된다."""
        self._tryout(tryout_no=1)
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self._tryout(tryout_no=1)

    # ───────── ② 누락(미이행) 판정 ─────────

    def test_tryout_missing_flags_active_mold(self):
        # 등록 상태에서는 누락이 아니다 (아직 양산에 쓰지 않는다)
        self.assertEqual(self.mold.state, "draft")
        self.assertFalse(self.mold.is_tryout_missing)

        # 사용 전환 → 합격 T/O 가 없으므로 누락
        self.mold.action_activate()
        self.assertTrue(self.mold.is_tryout_missing)
        self.assertIn(
            self.mold, self.env["iatf.mold"].search([("is_tryout_missing", "=", True)])
        )
        # 막지 않되 chatter 에 경고를 남긴다 (알고도 넣었다는 사실이 증빙에 남는다)
        self.assertTrue(
            self.mold.message_ids.filtered(lambda m: "시사출" in (m.body or "")),
            "경고가 chatter 에 기록되어야 한다",
        )

        # 작성 중인 보고서만으로는 해소되지 않는다
        to = self._tryout(conclusion="pass")
        self.mold.invalidate_recordset()
        self.assertTrue(self.mold.is_tryout_missing, "작성 중(draft)은 증빙이 아니다")

        # 재수정 판정으로 완료해도 해소되지 않는다
        to.conclusion = "rework"
        to.action_done()
        self.mold.invalidate_recordset()
        self.assertTrue(self.mold.is_tryout_missing, "재수정은 합격이 아니다")

        # 합격 + 완료라야 해소
        to.action_draft()
        to.conclusion = "pass"
        to.action_done()
        self.mold.invalidate_recordset()
        self.assertFalse(self.mold.is_tryout_missing)
        self.assertNotIn(
            self.mold, self.env["iatf.mold"].search([("is_tryout_missing", "=", True)])
        )

    # ───────── ③ 상·하한 벗어난 값의 합부 판정 ─────────

    def test_quantity_over_shot_count_rejected(self):
        with self.assertRaises(ValidationError, msg="양품+불량이 타수를 넘을 수 없다"):
            self._tryout(shot_count=50, ok_qty=48, ng_qty=5)

    def test_negative_quantity_rejected(self):
        with self.assertRaises(ValidationError):
            self._tryout(shot_count=50, ok_qty=-1, ng_qty=0)

    def test_quantity_within_shot_count_ok(self):
        to = self._tryout(shot_count=50, ok_qty=48, ng_qty=2)
        self.assertAlmostEqual(to.defect_rate, 4.0, places=2)

    def test_no_shot_count_skips_upper_bound(self):
        """타수를 안 적었으면 상한 검사를 걸 근거가 없다 — 막지 않는다."""
        to = self._tryout(shot_count=0, ok_qty=10, ng_qty=3)
        self.assertAlmostEqual(to.defect_rate, 23.08, places=2)
