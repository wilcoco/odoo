"""제3자 재검토(2026-09-10) R01·R02·R04 회귀 — 범용 점검 실적.

금형 점검과 같은 규칙을 쓰는 원장이라 같은 구멍이 있었다. 한쪽만 고치면 다시 갈라진다.
"""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCheckRecordLockR01R02(TransactionCase):

    def setUp(self):
        super().setUp()
        self.sheet = self.env["iatf.check.sheet"].create({
            "name": "R-점검시트", "code": "R-CS-01", "target_type": "facility",
            "cycle": "daily",
            "item_ids": [(0, 0, {"name": "칼날 마모", "check_method": "visual"})]})
        self.Record = self.env["iatf.check.record"]
        self.Line = self.env["iatf.check.record.line"]
        self.user = self.env["res.users"].create({
            "name": "R-점검원", "login": "r_we_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                self.env.ref("iatf_work_environment.group_work_environment_user").id])]})
        self.manager = self.env["res.users"].create({
            "name": "R-환경관리자", "login": "r_we_mgr",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                self.env.ref("iatf_work_environment.group_work_environment_manager").id])]})

    def _done_record(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        rec.line_ids.write({"result": "ok"})
        rec.action_done()
        self.assertEqual((rec.state, rec.overall_result), ("done", "ok"))
        return rec

    def test_r01_line_cannot_be_added_to_done_record(self):
        rec = self._done_record()
        with self.assertRaises(ValidationError):
            self.Line.with_user(self.user).create({
                "record_id": rec.id, "item_name": "추가 항목"})
        rec.invalidate_recordset()
        self.assertEqual(rec.overall_result, "ok")

    def test_r02_state_and_overall_cannot_be_written_together(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})   # 판정 비움
        self.assertEqual(rec.overall_result, "pending")
        with self.assertRaises(ValidationError):
            rec.with_user(self.user).write({"state": "done", "overall_result": "ok"})

    def test_r02_manager_cannot_delete_done_record(self):
        rec = self._done_record()
        with self.assertRaises(ValidationError):
            rec.with_user(self.manager).unlink()
        with self.assertRaises(ValidationError):
            rec.line_ids.with_user(self.manager).unlink()
        self.assertTrue(rec.exists())


@tagged("post_install", "-at_install")
class TestCheckRecordNaR04(TransactionCase):

    def setUp(self):
        super().setUp()
        self.sheet = self.env["iatf.check.sheet"].create({
            "name": "R-NA시트", "code": "R-CS-NA", "target_type": "facility", "cycle": "daily",
            "item_ids": [(0, 0, {"name": "AIR 압력", "check_method": "measure",
                                 "entry_type": "numeric", "spec_mode": "range",
                                 "spec_min": 0.4, "spec_max": 0.6, "uom_name": "Mpa"})]})
        self.Record = self.env["iatf.check.record"]

    def test_r04_na_without_reason_is_not_a_pass(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        rec.line_ids.write({"result": "na"})
        self.assertEqual(rec.overall_result, "pending")
        self.assertEqual(rec.na_count, 1)
        with self.assertRaises(UserError):
            rec.action_done()

    def test_r04_na_with_reason_is_a_judgement(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        rec.line_ids.write({"result": "na", "remark": "해당 설비 미가동 (정기보수)"})
        self.assertEqual(rec.overall_result, "ok")
        rec.action_done()
        self.assertEqual(rec.state, "done")


@tagged("post_install", "-at_install")
class TestAstraRepro2RecordEvidence(TransactionCase):
    """아스트라 독립재현 ② — 금형 점검과 같은 구멍. 한쪽만 고치면 다시 갈라진다."""

    def setUp(self):
        super().setUp()
        self.sheet = self.env["iatf.check.sheet"].create({
            "name": "A2-점검시트", "code": "A2-CS-01", "target_type": "facility",
            "cycle": "daily",
            "item_ids": [(0, 0, {"name": "칼날 마모", "check_method": "visual"})]})
        self.Record = self.env["iatf.check.record"]
        self.user = self.env["res.users"].create({
            "name": "A2-점검원", "login": "a2_we_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                self.env.ref("iatf_work_environment.group_work_environment_user").id])]})

    def _done_record(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        rec.line_ids.write({"result": "ok"})
        rec.action_done()
        return rec

    def test_was_done_cannot_be_cleared(self):
        rec = self._done_record()
        rec.action_draft()
        with self.assertRaises(ValidationError):
            rec.write({"was_done": False})
        self.assertTrue(rec.was_done)
        with self.assertRaises(ValidationError):
            rec.unlink()

    def test_record_cannot_be_born_done(self):
        """완료 상태로 바로 만들 수 없다 — 시트에서 채워진 라인이 미판정이다.

        이 경로가 열려 있으면 create(done) → write(draft) → unlink 로 완료 이력을
        남기지 않고 증빙을 만들었다 지울 수 있다.
        """
        with self.assertRaises(ValidationError):
            self.Record.create({"sheet_id": self.sheet.id, "state": "done"})
        self.assertFalse(self.Record.search([("sheet_id", "=", self.sheet.id)]),
                         "완료 상태로 태어난 실적이 남았다")

    def test_lines_of_a_reverted_record_cannot_be_deleted(self):
        rec = self._done_record()
        rec.action_draft()
        with self.assertRaises(ValidationError):
            rec.line_ids.with_user(self.user).unlink()
        self.assertTrue(rec.line_ids, "완료 증빙의 항목이 지워졌다")

    def test_reverted_record_can_still_be_corrected(self):
        rec = self._done_record()
        rec.action_draft()
        rec.line_ids.write({"result": "ng"})
        self.assertEqual(rec.overall_result, "issue")

    def test_unjudged_line_cannot_be_reparented_into_a_done_record(self):
        done = self._done_record()
        draft = self.Record.create({"sheet_id": self.sheet.id})
        draft.line_ids.write({"result": False})
        with self.assertRaises(ValidationError):
            draft.line_ids[0].write({"record_id": done.id})
        done.invalidate_recordset()
        self.assertEqual((done.state, done.overall_result), ("done", "ok"))


@tagged("post_install", "-at_install")
class TestCompletionSnapshotRecord(TransactionCase):
    """아스트라 후속 — 금형 점검과 같은 규칙. 한쪽만 고치면 다시 갈라진다."""

    def setUp(self):
        super().setUp()
        self.sheet = self.env["iatf.check.sheet"].create({
            "name": "S-점검시트", "code": "S-CS-01", "target_type": "facility",
            "cycle": "daily",
            "item_ids": [(0, 0, {"name": "칼날 마모", "check_method": "visual"})]})
        self.Record = self.env["iatf.check.record"]

    def _done_record(self, result="ok"):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        rec.line_ids.write({"result": result})
        rec.action_done()
        return rec

    def test_completion_writes_a_snapshot(self):
        rec = self._done_record()
        self.assertEqual(rec.snapshot_count, 1)
        self.assertEqual(rec.snapshot_ids.revision, 1)
        self.assertIn("칼날 마모", rec.snapshot_ids.content)

    def test_correction_keeps_the_earlier_judgement(self):
        rec = self._done_record(result="ok")
        rec.action_draft()
        rec.line_ids.write({"result": "ng"})
        rec.action_done()
        self.assertEqual(rec.snapshot_count, 2)
        first = rec.snapshot_ids.filtered(lambda s: s.revision == 1)
        second = rec.snapshot_ids.filtered(lambda s: s.revision == 2)
        self.assertIn('"판정": "ok"', first.content,
                      "처음 완료 시점의 판정이 사라졌다")
        self.assertIn('"판정": "ng"', second.content)

    def test_snapshots_cannot_be_edited_or_deleted(self):
        rec = self._done_record()
        with self.assertRaises(ValidationError):
            rec.snapshot_ids.write({"content": "[]"})
        with self.assertRaises(ValidationError):
            rec.snapshot_ids.unlink()


@tagged("post_install", "-at_install")
class TestRecordSnapshotEvidenceIntegrity(TransactionCase):
    """아스트라 275 리뷰 Q275-01·02·03 — 금형 점검과 같은 규칙."""

    def setUp(self):
        super().setUp()
        self.sheet = self.env["iatf.check.sheet"].create({
            "name": "E-점검시트", "code": "E-CS-01", "target_type": "facility",
            "cycle": "daily",
            "item_ids": [(0, 0, {"name": "칼날 마모", "check_method": "visual"})]})
        self.Record = self.env["iatf.check.record"]
        self.Snapshot = self.env["iatf.check.record.snapshot"]
        self.user = self.env["res.users"].create({
            "name": "E-점검원", "login": "e_we_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                self.env.ref("iatf_work_environment.group_work_environment_user").id])]})

    def _draft(self, result="ok"):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        rec.line_ids.write({"result": result})
        return rec

    def test_a_user_cannot_forge_a_snapshot(self):
        rec = self._draft()
        with self.assertRaises(Exception) as caught:
            self.Snapshot.with_user(self.user).create({
                "record_id": rec.id, "revision": 99,
                "done_at": "2026-09-09 00:00:00", "line_count": 100, "content": "[]"})
        self.assertIsInstance(caught.exception, (AccessError, ValidationError))
        self.assertEqual(rec.snapshot_count, 0)

    def test_snapshot_of_an_uncompleted_record_is_refused(self):
        rec = self._draft()
        Snap = self.Snapshot.sudo()
        with self.assertRaises(ValidationError):
            Snap.with_context(**{Snap._SERVICE_KEY: True}).create({"record_id": rec.id})

    def test_forged_overall_result_is_refused_on_completion(self):
        rec = self._draft(result="ng")
        with self.assertRaises(ValidationError):
            rec.with_user(self.user).write({"state": "done", "overall_result": "ok"})
        self.assertEqual(rec.snapshot_count, 0)

    def test_snapshot_records_the_derived_result(self):
        rec = self._draft(result="ng")
        rec.action_done()
        snap = rec.snapshot_ids
        self.assertEqual(snap.overall_result, "이상 있음")
        self.assertEqual(snap.ng_count, 1)

    def test_header_identity_is_frozen(self):
        rec = self._draft()
        rec.action_done()
        snap = rec.snapshot_ids
        self.assertEqual(snap.sheet_id, self.sheet)
        self.assertEqual(snap.sheet_revision, rec.sheet_revision)
        self.assertEqual(snap.check_date, rec.check_date)
        self.assertTrue(snap.company_name)
