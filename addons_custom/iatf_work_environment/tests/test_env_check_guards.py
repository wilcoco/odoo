"""478 #40 — 작업환경 점검: 세부 부적합이 있으면 전체 적합으로 완료하지 못한다."""
from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEnvironmentCheckGuards(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Check = cls.env["iatf.environment.check"]
        cls.area = cls.env["iatf.work.area"].create({"name": "478A 시험 구역"})

    def _check(self, **line):
        values = dict(item_name="조도", standard="300 lx 이상")
        values.update(line)
        return self.Check.create({
            "work_area_id": self.area.id,
            "line_ids": [Command.create(values)],
        })

    def test_new_line_is_pending(self):
        rec = self._check()
        self.assertEqual(rec.line_ids.result, "pending")
        self.assertEqual(rec.pending_count, 1)
        rec.result = "pass"
        with self.assertRaises(UserError):
            rec.action_done()

    def test_ng_line_blocks_overall_pass(self):
        rec = self._check(measured_value="120", result="ng")
        rec.result = "pass"
        with self.assertRaises(UserError):
            rec.action_done()
        rec.result = "action"
        with self.assertRaises(UserError):
            rec.action_done()          # 조치 내용이 없다
        rec.corrective_action = "조도 보강 작업 의뢰"
        rec.action_done()
        self.assertEqual(rec.state, "done")

    def test_ok_without_measurement_is_pending(self):
        rec = self._check(result="ok")
        self.assertEqual(rec.pending_count, 1)
        rec.result = "pass"
        with self.assertRaises(UserError):
            rec.action_done()
        rec.line_ids.measured_value = "350"
        rec.action_done()
        self.assertEqual(rec.state, "done")

    def test_na_requires_remark(self):
        rec = self._check(result="na")
        rec.result = "pass"
        with self.assertRaises(UserError):
            rec.action_done()
        rec.line_ids.remark = "해당 구역 없음"
        rec.line_ids.measured_value = "-"
        rec.action_done()
        self.assertEqual(rec.state, "done")

    # ── 533 §2 완료 뒤 보호 (아스트라 A-40-S01) ──────────────────
    def _done(self):
        """정상 완료된 점검 하나.

        `_check(**line)` 의 인자는 **항목**으로 들어간다. 머리글 판정은
        따로 넣어야 한다.
        """
        rec = self._check(result="ok", measured_value="320 lx")
        rec.result = "pass"
        rec.action_done()
        self.assertEqual(rec.state, "done")
        return rec

    def test_overall_result_locked_after_done(self):
        rec = self._done()
        with self.assertRaises(UserError):
            rec.result = "pass"
        with self.assertRaises(UserError):
            rec.write({"state": "draft"})
        self.assertEqual(rec.state, "done")

    def test_lines_locked_after_done(self):
        rec = self._done()
        line = rec.line_ids[:1]
        with self.assertRaises(UserError):
            line.result = "ng"
        with self.assertRaises(UserError):
            line.unlink()
        with self.assertRaises(UserError):
            self.env["iatf.environment.check.line"].create({
                "check_id": rec.id, "item_name": "추가 항목",
            })

    def test_reopen_requires_reason_then_allows_correction(self):
        rec = self._done()
        with self.assertRaises(UserError):
            rec.action_reopen(reason="   ")
        rec.action_reopen(reason="측정값 오기재 정정")
        self.assertEqual(rec.state, "draft")
        rec.line_ids[:1].result = "ng"
        self.assertEqual(rec.line_ids[:1].result, "ng")

    def test_plain_context_cannot_forge_reopen(self):
        rec = self._done()
        for value in (True, 1, "yes"):
            with self.assertRaises(UserError):
                rec.with_context(env_check_reopen=value).write({"result": "pass"})

    # ── 아스트라 A-40-S02: 완료 진입 경로 ────────────────────────
    def test_direct_done_write_from_draft_is_blocked(self):
        """초안에 상태만 '완료' 로 써서 판정 검사를 지나갈 수 없다."""
        rec = self._check(result="ng")      # 항목 부적합
        rec.result = "pass"                 # 모순: 전체 적합
        with self.assertRaises(UserError):
            rec.action_done()               # 정상 대조 — 버튼은 모순을 잡는다
        with self.assertRaises(UserError):
            rec.write({"state": "done"})    # 직접 쓰기도 막힌다
        self.assertEqual(rec.state, "draft")

    def test_cannot_create_done_directly(self):
        """처음부터 '완료' 로 만들 수 없다."""
        with self.assertRaises(UserError):
            self.Check.create({
                "work_area_id": self.area.id,
                "state": "done",
                "line_ids": [Command.create({"item_name": "조도"})],
            })

    def test_plain_context_cannot_forge_completion(self):
        rec = self._check(result="ng")
        rec.result = "pass"
        for value in (True, 1, "yes"):
            with self.assertRaises(UserError):
                rec.with_context(env_check_completing=value).write({"state": "done"})
        self.assertEqual(rec.state, "draft")

    # ── 아스트라 040 §3 (A-40-S02 범위) ───────────────────────────
    def test_done_entry_guard_survives_lock_off(self):
        """완료 **진입** 검증은 완료 후 **잠금** 설정과 분리되어야 한다.

        두 가드를 한 설정에 묶으면, 잠금을 끈 회사에서 완료 상태 직접 쓰기·
        직접 생성까지 열려 완료 버튼의 판정 검사가 통째로 빠진다.
        """
        param = self.env["ir.config_parameter"].sudo()
        param.set_param("quality.env_check_lock_after_done", "0")
        rec = self._check(measured_value="120", result="ng")
        rec.result = "pass"
        with self.assertRaisesRegex(UserError, "완료 버튼"):
            rec.write({"state": "done"})
        self.assertNotEqual(rec.state, "done")
        with self.assertRaisesRegex(UserError, "완료 상태로 바로"):
            self.Check.create({
                "work_area_id": self.area.id, "state": "done",
                "result": "pass",
                "line_ids": [Command.create({
                    "item_name": "조도", "standard": "300 lx 이상",
                    "measured_value": "120", "result": "ng"})]})
        # 진입 검증 자체를 끄려면 전용 설정을 쓴다.
        param.set_param("quality.env_check_require_done_button", "0")
        rec.write({"state": "done"})
        self.assertEqual(rec.state, "done")

    def test_done_entry_guard_default_on_without_any_setting(self):
        rec = self._check(measured_value="120", result="ng")
        rec.result = "pass"
        with self.assertRaisesRegex(UserError, "완료 버튼"):
            rec.write({"state": "done"})
