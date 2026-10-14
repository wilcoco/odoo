"""제3자 재검토(2026-09-10) R01~R04 회귀 — 금형 점검·온도 이력.

각 시험은 재검토 문서가 **실제로 재현한 우회 경로**를 그대로 따라간다.
막혔는지만 보는 게 아니라, 막힌 뒤에도 사실이 그대로인지(판정·스냅샷)까지 본다.
"""
from odoo import fields
from odoo.exceptions import UserError, AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoldCheckLockR01R02(TransactionCase):
    """R01·R02 — 완료 점검표 잠금의 구멍."""

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({
            "name": "R-금형", "mold_type": "injection", "check_cycle_days": 7})
        self.Check = self.env["iatf.mold.check"]
        self.Line = self.env["iatf.mold.check.line"]
        self.user = self.env["res.users"].create({
            "name": "R-점검자", "login": "r_mold_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_user").id])]})
        self.manager = self.env["res.users"].create({
            "name": "R-금형관리자", "login": "r_mold_mgr",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_manager").id])]})

    def _done_check(self):
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "형면 이물", "result": "ok"})]})
        chk.action_done()
        self.assertEqual((chk.state, chk.overall_result), ("done", "ok"))
        return chk

    def test_r01_line_cannot_be_added_to_done_check(self):
        """완료·양호였던 점검표에 미판정 라인을 달아 '완료·미판정' 으로 만들 수 없다.

        부모 write 잠금은 `line_ids` 경로만 막는다. 라인 모델에 직접 create 하면
        그 경로를 타지 않아 통과했다 — 재검토가 일반 담당자 권한으로 재현한 것.
        """
        chk = self._done_check()
        with self.assertRaises(ValidationError):
            self.Line.with_user(self.user).create({
                "check_id": chk.id, "item_name": "슬라이드", "result": False})
        chk.invalidate_recordset()
        self.assertEqual(chk.overall_result, "ok", "완료 실적의 종합 판정이 바뀌었다")
        self.assertEqual(len(chk.line_ids), 1)

    def test_r02_state_and_overall_cannot_be_written_together(self):
        """`{state:'done', overall_result:'ok'}` 동시 쓰기로 미판정 점검표를 완료할 수 없다.

        저장된 종합 판정을 백스톱이 그대로 믿으면, 재계산이 돌지 않아 통과한다.
        """
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "형면 이물"})]})   # 판정 비움
        self.assertEqual(chk.overall_result, "pending")
        with self.assertRaises(ValidationError):
            chk.with_user(self.user).write({"state": "done", "overall_result": "ok"})

    def test_r02_manager_cannot_delete_done_check(self):
        """모듈 관리자도 완료된 점검표를 지울 수 없다."""
        chk = self._done_check()
        with self.assertRaises(ValidationError):
            chk.with_user(self.manager).unlink()
        with self.assertRaises(ValidationError):
            chk.line_ids.with_user(self.manager).unlink()
        self.assertTrue(chk.exists())

    def test_draft_then_edit_then_done_still_works(self):
        """잠금이 정상 정정 경로까지 막지는 않는다."""
        chk = self._done_check()
        chk.action_draft()
        self.Line.create({"check_id": chk.id, "item_name": "슬라이드", "result": "ok"})
        chk.action_done()
        self.assertEqual((chk.state, chk.overall_result), ("done", "ok"))
        self.assertEqual(len(chk.line_ids), 2)


@tagged("post_install", "-at_install")
class TestMoldTempSnapshotR03(TransactionCase):
    """R03 — 온도 스냅샷이 재입력으로 갈아치워지던 경로."""

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({
            "name": "R-온도금형", "mold_type": "injection",
            "preheat_temp_min": 60.0, "preheat_temp_max": 90.0})
        self.Log = self.env["iatf.mold.temp.log"]
        self.user = self.env["res.users"].create({
            "name": "R-측정자", "login": "r_temp_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_user").id])]})

    def _log(self, **vals):
        base = {"mold_id": self.mold.id, "log_type": "preheat", "point": "fixed",
                "method": "ir", "temperature": 95.0}
        base.update(vals)
        return self.Log.create(base)

    def test_r03_rewriting_mold_does_not_refresh_snapshot(self):
        """마스터 상한을 넓힌 뒤 **같은 금형 ID 를 재입력해도** 과거 판정은 그대로다.

        재검토가 재현한 경로: 스냅샷이 계산 필드라 `mold_id` write 가 재계산을 트리거해
        90 → 100 으로 갈아치워지고 부적합이 적합으로 뒤집혔다.
        """
        log = self._log()
        self.assertEqual((log.spec_min, log.spec_max, log.spec_result), (60.0, 90.0, "ng"))
        self.mold.preheat_temp_max = 100.0
        with self.assertRaises(ValidationError):
            log.write({"mold_id": self.mold.id})
        log.invalidate_recordset()
        self.assertEqual(log.spec_max, 90.0, "스냅샷이 현행 마스터로 갈아치워졌다")
        self.assertEqual(log.spec_result, "ng", "과거 판정이 뒤집혔다")
        self.assertEqual(log.current_spec_result, "ok", "현행 기준 재평가는 참고값으로 보여야 한다")

    def test_r03_result_cannot_be_hand_written(self):
        """합부만 직접 고쳐 부적합을 양호로 바꿀 수 없다."""
        log = self._log()
        for vals in ({"spec_result": "ok"}, {"spec_max": 100.0}, {"temperature": 70.0}):
            with self.assertRaises(ValidationError):
                log.with_user(self.user).write(vals)
        log.invalidate_recordset()
        self.assertEqual(log.spec_result, "ng")

    def test_r03_snapshot_ignores_caller_supplied_spec(self):
        """호출자가 상·하한을 직접 넘겨도 마스터 값으로 덮는다."""
        log = self._log(spec_min=0.0, spec_max=999.0)
        self.assertEqual((log.spec_min, log.spec_max), (60.0, 90.0))
        self.assertEqual(log.spec_result, "ng")

    def test_new_log_after_revision_uses_new_spec(self):
        """개정 뒤 새로 잰 기록은 새 기준으로 판정된다."""
        self.mold.preheat_temp_max = 100.0
        log = self._log()
        self.assertEqual((log.spec_max, log.spec_result), (100.0, "ok"))

    def test_notes_stay_editable(self):
        """측정 사실이 아닌 비고는 고칠 수 있어야 한다."""
        log = self._log()
        log.write({"notes": "재측정 예정"})
        self.assertEqual(log.notes, "재측정 예정")


@tagged("post_install", "-at_install")
class TestMoldNaR04(TransactionCase):
    """R04 — 기준 있는 항목의 사유 없는 '해당없음'."""

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({"name": "R-NA금형", "mold_type": "injection"})
        self.Check = self.env["iatf.mold.check"]

    def _check(self, **line):
        base = {"item_name": "형체 온도", "spec_min": 10.0, "spec_max": 20.0, "result": "na"}
        base.update(line)
        return self.Check.create({"mold_id": self.mold.id, "check_type": "daily",
                                  "line_ids": [(0, 0, base)]})

    def test_r04_na_without_reason_is_not_a_pass(self):
        """기준이 있는 수치 항목을 사유 없이 '해당없음' 으로 두면 종합은 '미완료'."""
        chk = self._check()
        self.assertEqual(chk.overall_result, "pending")
        self.assertEqual(chk.na_count, 1)
        # action_done 은 UserError 를 던진다. ValidationError ⊂ UserError 라
        # 상위 클래스로 받아 두 경로(버튼·백스톱)를 모두 덮는다.
        with self.assertRaises(UserError):
            chk.action_done()

    def test_r04_na_with_reason_is_a_judgement(self):
        """제외 사유를 적으면 판정으로 인정한다 — 새 승인 절차를 만들지 않는다."""
        chk = self._check(remark="설비 개조로 해당 부위 제거됨 (2026-09-10 생산기술 확인)")
        self.assertEqual(chk.overall_result, "ok")
        chk.action_done()
        self.assertEqual(chk.state, "done")

    def test_r04_qualitative_na_needs_no_reason(self):
        """기준이 없는 정성 항목의 '해당없음' 은 원래대로 사유 없이도 정상이다."""
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "이물 부착", "result": "na"})]})
        self.assertEqual(chk.overall_result, "ok")


@tagged("post_install", "-at_install")
class TestAstraReview2(TransactionCase):
    """아스트라 재검토(2026-09-10) ①② — 유효 측정 0, 완료→작성중→삭제 우회."""

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({"name": "A-금형", "mold_type": "injection"})
        self.Check = self.env["iatf.mold.check"]
        self.manager = self.env["res.users"].create({
            "name": "A-관리자", "login": "a_mold_mgr",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_manager").id])]})

    def _done_check(self):
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "형면 이물", "result": "ok"})]})
        chk.action_done()
        return chk

    def test_draft_then_delete_is_blocked(self):
        """'작성 중' 으로 되돌린 뒤에도 완료 이력이 있는 기록은 지울 수 없다.

        state 만 보는 잠금은 되돌리기 한 번으로 무력화된다. 삭제를 막는 근거는
        **지금 상태**가 아니라 **완료된 적이 있다는 사실**이어야 한다.
        """
        chk = self._done_check()
        self.assertTrue(chk.was_done)
        chk.action_draft()
        self.assertEqual(chk.state, "draft")
        self.assertTrue(chk.was_done, "되돌렸다고 완료 이력이 지워지면 안 된다")
        with self.assertRaises(ValidationError):
            chk.with_user(self.manager).unlink()
        self.assertTrue(chk.exists())

    def test_line_cannot_be_moved_out_of_completed_check(self):
        """되돌린 뒤 라인을 다른 점검표로 옮겨 증빙을 비울 수 없다."""
        chk = self._done_check()
        other = self.Check.create({"mold_id": self.mold.id, "check_type": "daily"})
        chk.action_draft()
        with self.assertRaises(ValidationError):
            chk.line_ids.write({"check_id": other.id})
        self.assertEqual(len(chk.line_ids), 1)

    def test_never_completed_draft_can_still_be_deleted(self):
        """한 번도 완료된 적 없는 초안은 지울 수 있어야 한다 — 잠금이 과하지 않은지."""
        chk = self.Check.create({"mold_id": self.mold.id, "check_type": "daily"})
        self.assertFalse(chk.was_done)
        chk.with_user(self.manager).unlink()
        self.assertFalse(chk.exists())


@tagged("post_install", "-at_install")
class TestAstraRepro2MoldEvidence(TransactionCase):
    """아스트라 독립재현 ② — 완료 이력 해제·되돌린 뒤 자식 삭제·완료 부모로 reparent."""

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({"name": "A2-금형", "mold_type": "injection"})
        self.Check = self.env["iatf.mold.check"]
        self.Line = self.env["iatf.mold.check.line"]
        self.user = self.env["res.users"].create({
            "name": "A2-점검원", "login": "a2_mold_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_user").id])]})

    def _done_check(self):
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "형면 이물", "result": "ok"})]})
        chk.action_done()
        return chk

    def test_was_done_cannot_be_cleared(self):
        chk = self._done_check()
        chk.action_draft()
        with self.assertRaises(ValidationError):
            chk.write({"was_done": False})
        self.assertTrue(chk.was_done)
        with self.assertRaises(ValidationError):
            chk.unlink()
        self.assertTrue(chk.exists())

    def test_check_cannot_be_born_done(self):
        """완료 상태로 바로 만들 수 없다 — 완료는 판정을 마친 뒤의 상태다.

        이 경로가 열려 있으면 create(done) → write(draft) → unlink 로 완료 이력을
        남기지 않고 증빙을 만들었다 지울 수 있다. 라인 없이 만들면 완성도 검사가,
        라인과 함께 만들면 '완료된 점검표에 항목 추가 금지'가 막는다.
        """
        base = {"mold_id": self.mold.id, "check_type": "daily", "state": "done"}
        with self.assertRaises(ValidationError):
            self.Check.create(dict(base))
        with self.assertRaises(ValidationError):
            self.Check.create(dict(
                base, line_ids=[(0, 0, {"item_name": "형면 이물", "result": "ok"})]))
        self.assertFalse(self.Check.search([("mold_id", "=", self.mold.id)]),
                         "완료 상태로 태어난 점검표가 남았다")

    def test_lines_of_a_reverted_check_cannot_be_deleted(self):
        chk = self._done_check()
        chk.action_draft()
        with self.assertRaises(ValidationError):
            chk.line_ids.with_user(self.user).unlink()
        with self.assertRaises(ValidationError):
            chk.with_user(self.user).write({"line_ids": [(2, chk.line_ids.id)]})
        self.assertEqual(len(chk.line_ids), 1, "완료 증빙의 항목이 지워졌다")

    def test_reverted_check_can_still_be_corrected(self):
        """삭제는 막되 값 수정은 열려 있어야 한다 — 그러라고 되돌리는 것이다."""
        chk = self._done_check()
        chk.action_draft()
        chk.line_ids.write({"result": "ng"})
        self.assertEqual(chk.overall_result, "issue")

    def test_unjudged_line_cannot_be_reparented_into_a_done_check(self):
        """완료된 점검표에 미판정 라인을 옮겨 붙일 수 없다."""
        done = self._done_check()
        draft = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "미판정 항목"})]})
        self.assertFalse(draft.line_ids.result)
        with self.assertRaises(ValidationError):
            draft.line_ids.write({"check_id": done.id})
        done.invalidate_recordset()
        self.assertEqual((done.state, done.overall_result), ("done", "ok"))


@tagged("post_install", "-at_install")
class TestCompletionSnapshotMold(TransactionCase):
    """아스트라 후속 — 완료 시점의 측정값 전문이 남는다.

    되돌려 고치고 다시 완료하면 '지금 값' 만 남고 처음 완료했을 때의 값이 사라졌다.
    심사에서 묻는 것은 '그때 그렇게 판정했는가' 다.
    """

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({"name": "S-금형", "mold_type": "injection"})
        self.Check = self.env["iatf.mold.check"]
        self.user = self.env["res.users"].create({
            "name": "S-점검원", "login": "s_mold_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_user").id])]})

    def _done_check(self, value=50.0):
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "형면 온도", "spec_min": 40.0,
                                 "spec_max": 60.0, "value": value})]})
        chk.action_done()
        return chk

    def test_completion_writes_a_snapshot(self):
        chk = self._done_check()
        self.assertEqual(chk.snapshot_count, 1)
        snap = chk.snapshot_ids
        self.assertEqual(snap.revision, 1)
        self.assertEqual(snap.line_count, 1)
        self.assertIn("형면 온도", snap.content)
        self.assertIn("50.0", snap.content)
        self.assertTrue(snap.done_at)

    def test_correction_keeps_the_earlier_measurement(self):
        chk = self._done_check(value=50.0)
        chk.action_draft()
        chk.line_ids.write({"value": 55.0})
        chk.action_done()
        self.assertEqual(chk.snapshot_count, 2, "다시 완료했는데 차수가 오르지 않았다")
        first = chk.snapshot_ids.filtered(lambda s: s.revision == 1)
        second = chk.snapshot_ids.filtered(lambda s: s.revision == 2)
        self.assertIn("50.0", first.content, "처음 완료 시점의 측정값이 사라졌다")
        self.assertIn("55.0", second.content)

    def test_snapshots_cannot_be_edited_or_deleted(self):
        chk = self._done_check()
        snap = chk.snapshot_ids
        with self.assertRaises(ValidationError):
            snap.write({"content": "[]"})
        with self.assertRaises(ValidationError):
            snap.with_user(self.user).unlink()
        self.assertTrue(snap.exists())

    def test_no_snapshot_while_still_draft(self):
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "이물", "result": "ok"})]})
        self.assertEqual(chk.snapshot_count, 0)


@tagged("post_install", "-at_install")
class TestSnapshotEvidenceIntegrity(TransactionCase):
    """아스트라 275 리뷰 Q275-01·02·03 — 스냅샷은 지어낼 수 없고, 집계는 항목이 정한다."""

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({"name": "E-금형", "mold_type": "injection"})
        self.other_mold = self.env["iatf.mold"].create({"name": "E-금형2", "mold_type": "injection"})
        self.Check = self.env["iatf.mold.check"]
        self.Snapshot = self.env["iatf.mold.check.snapshot"]
        self.user = self.env["res.users"].create({
            "name": "E-점검원", "login": "e_mold_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_user").id])]})

    def _draft(self, **line):
        return self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, dict({"item_name": "형면 이물", "result": "ok"}, **line))]})

    def _assert_blocked(self, func):
        """권한(AccessError)으로 막히든 규칙(ValidationError)으로 막히든 막히면 된다.

        (Odoo 의 assertRaises 는 예외 튜플을 받지 못한다.)
        """
        with self.assertRaises(Exception) as caught:
            func()
        self.assertIsInstance(caught.exception, (AccessError, ValidationError))

    # ── Q275-01 ──
    def test_a_user_cannot_forge_a_snapshot_on_a_draft(self):
        chk = self._draft()
        self._assert_blocked(lambda: self.Snapshot.with_user(self.user).create({
            "check_id": chk.id, "revision": 99,
            "done_at": "2026-09-09 00:00:00", "done_by_id": self.env.user.id,
            "overall_result": "양호", "line_count": 100,
            "content": '[{"항목":"실시하지 않은 검사","판정":"ok"}]'}))
        self.assertEqual(chk.snapshot_count, 0)

    def test_context_defaults_do_not_open_a_side_door(self):
        chk = self._draft()
        self._assert_blocked(lambda: self.Snapshot.with_user(self.user).with_context(
            default_check_id=chk.id, default_revision=99,
            default_content="[]").create({}))

    def test_one2many_command_cannot_attach_a_snapshot(self):
        chk = self._draft()
        self._assert_blocked(lambda: chk.with_user(self.user).write({
            "snapshot_ids": [(0, 0, {"revision": 99, "done_at": "2026-09-09 00:00:00",
                                     "content": "[]"})]}))
        self.assertEqual(chk.snapshot_count, 0)

    def test_even_sudo_cannot_hand_pick_snapshot_values(self):
        """서비스 경로로 들어와도 값은 서버가 만든다 — 부모 id 만 받는다."""
        chk = self._draft()
        chk.action_done()
        Snap = self.Snapshot.sudo()
        forged = Snap.with_context(**{Snap._SERVICE_KEY: True}).create({
            "check_id": chk.id, "revision": 99, "line_count": 100,
            "overall_result": "이상 있음", "content": "[]"})
        self.assertEqual(forged.revision, 2, "호출자가 준 차수가 그대로 저장됐다")
        self.assertEqual(forged.line_count, 1)
        self.assertEqual(forged.overall_result, "양호")
        self.assertIn("형면 이물", forged.content)

    def test_snapshot_of_an_uncompleted_check_is_refused(self):
        chk = self._draft()
        Snap = self.Snapshot.sudo()
        with self.assertRaises(ValidationError):
            Snap.with_context(**{Snap._SERVICE_KEY: True}).create({"check_id": chk.id})

    def test_revision_is_unique_per_check(self):
        chk = self._draft()
        chk.action_done()
        chk.action_draft()
        chk.action_done()
        self.assertEqual(sorted(chk.snapshot_ids.mapped("revision")), [1, 2])

    # ── Q275-02 ──
    def test_forged_overall_result_is_refused_on_completion(self):
        """NG 항목이 있는데 '양호' 로 완료할 수 없다."""
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "형면 온도", "spec_min": 40.0,
                                 "spec_max": 60.0, "value": 70.0})]})
        self.assertEqual(chk.line_ids.result, "ng")
        with self.assertRaises(ValidationError):
            chk.with_user(self.user).write({"state": "done", "overall_result": "ok"})
        self.assertEqual(chk.snapshot_count, 0)

    def test_snapshot_records_the_derived_result_not_the_stored_one(self):
        chk = self.Check.create({
            "mold_id": self.mold.id, "check_type": "daily",
            "line_ids": [(0, 0, {"item_name": "형면 온도", "spec_min": 40.0,
                                 "spec_max": 60.0, "value": 70.0})]})
        chk.action_done()
        snap = chk.snapshot_ids
        self.assertEqual(snap.overall_result, "이상 있음")
        self.assertEqual(snap.ng_count, 1)
        self.assertIn('"판정": "ng"', snap.content)

    # ── Q275-03 ──
    def test_header_identity_is_frozen_at_completion(self):
        chk = self._draft()
        original_date = chk.check_date
        chk.action_done()
        first = chk.snapshot_ids.filtered(lambda s: s.revision == 1)
        self.assertEqual(first.mold_id, self.mold)
        self.assertEqual(first.check_date, original_date)
        self.assertTrue(first.company_name)

        chk.action_draft()
        chk.write({"mold_id": self.other_mold.id})
        chk.action_done()
        first.invalidate_recordset()
        self.assertEqual(first.mold_id, self.mold,
                         "되돌려 금형을 바꿨더니 과거 스냅샷의 금형까지 바뀌었다")
        second = chk.snapshot_ids.filtered(lambda s: s.revision == 2)
        self.assertEqual(second.mold_id, self.other_mold)

    def test_snapshot_company_does_not_follow_the_parent(self):
        chk = self._draft()
        chk.action_done()
        snap = chk.snapshot_ids
        original = snap.company_id
        other = self.env["res.company"].create({"name": "E-회사B"})
        # 완료 잠금 때문에 ORM 으로는 부모 회사를 못 바꾼다. 필드 정의(복사본 vs related)
        # 자체를 보려는 시험이므로 컬럼을 직접 바꿔 최악의 경우를 만든다.
        self.env.cr.execute("UPDATE iatf_mold_check SET company_id = %s WHERE id = %s",
                            (other.id, chk.id))
        chk.invalidate_recordset()
        snap.invalidate_recordset()
        self.assertEqual(snap.company_id, original,
                         "부모 회사를 바꿨더니 과거 증빙의 회사가 따라 바뀌었다")


@tagged("post_install", "-at_install")
class TestSnapshotCompanyIsolation(TransactionCase):
    """아스트라 305 품질 리뷰 (2)(3) — 회사 복사와 **조회 격리**는 별개다."""

    def setUp(self):
        super().setUp()
        self.company_b = self.env["res.company"].create({"name": "S-회사B"})
        self.env.user.company_ids = [(4, self.company_b.id)]
        self.mold_b = self.env["iatf.mold"].with_context(
            allowed_company_ids=[self.env.company.id, self.company_b.id]).create({
                "name": "S-금형B", "mold_type": "injection",
                "company_id": self.company_b.id})
        self.user_a = self.env["res.users"].create({
            "name": "S-A전용", "login": "s_only_a",
            "company_id": self.env.company.id,
            "company_ids": [(6, 0, [self.env.company.id])],
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_mold.group_mold_user").id])]})

    def _done_check_of_b(self):
        chk = self.env["iatf.mold.check"].with_context(
            allowed_company_ids=[self.env.company.id, self.company_b.id]).create({
                "mold_id": self.mold_b.id, "check_type": "daily",
                "company_id": self.company_b.id,
                "line_ids": [(0, 0, {"item_name": "형면 이물", "result": "ok"})]})
        chk.action_done()
        return chk

    def test_other_company_snapshot_is_not_searchable(self):
        chk = self._done_check_of_b()
        self.assertTrue(chk.snapshot_ids)
        found = self.env["iatf.mold.check.snapshot"].with_user(self.user_a).search(
            [("id", "in", chk.snapshot_ids.ids)])
        self.assertFalse(found, "다른 회사의 완료 증빙이 조회된다")

    def test_snapshot_counts_match_its_own_content(self):
        """(3) 요약 숫자와 본문이 같은 근거에서 나온다."""
        import json
        chk = self.env["iatf.mold.check"].create({
            "mold_id": self.env["iatf.mold"].create(
                {"name": "S-금형A", "mold_type": "injection"}).id,
            "check_type": "daily",
            "line_ids": [
                (0, 0, {"item_name": "온도", "spec_min": 40.0, "spec_max": 60.0,
                        "value": 70.0}),
                (0, 0, {"item_name": "이물", "result": "ok"}),
            ]})
        chk.action_done()
        snap = chk.snapshot_ids
        payload = json.loads(snap.content)
        self.assertEqual(snap.line_count, len(payload))
        self.assertEqual(snap.ng_count,
                         len([row for row in payload if row["판정"] == "ng"]))
        self.assertEqual(snap.overall_result, "이상 있음")
