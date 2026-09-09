from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCheckSheet(TransactionCase):
    """범용 점검 시트 — 요청서 4항이 요구한 3종(정상 기록 / 기한 경과 / 상하한 합부)
    을 포함하고, 그 위에 '깨뜨리는' 케이스를 더 넣는다."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Sheet = cls.env["iatf.check.sheet"]
        cls.Record = cls.env["iatf.check.record"]
        cls.today = fields.Date.context_today(cls.Sheet)

        # 분쇄기 일상점검 (SQ 사출 3_4) — 정량 항목 + 정성 항목 혼합
        cls.sheet = cls.Sheet.create({
            "name": "분쇄기 #1 일상점검",
            "code": "CS-CRUSH-01",
            "target_type": "facility",
            "cycle": "daily",
            "start_date": cls.today,
            "item_ids": [
                (0, 0, {"name": "칼날 마모·파손", "check_method": "visual",
                        "standard": "균열·결손 없을 것"}),
                (0, 0, {"name": "스크린 눈막힘", "check_method": "visual"}),
                (0, 0, {"name": "재생재 배합비율", "check_method": "measure",
                        "spec_min": 0.0, "spec_max": 20.0, "uom_name": "%"}),
            ],
        })

    def _fill(self, record, values):
        """항목명 → 값 으로 라인을 채운다."""
        for line in record.line_ids:
            if line.item_name in values:
                line.write(values[line.item_name])

    # ── ① 정상 기록 생성 ──────────────────────────────────────────────

    def test_record_copies_items_from_sheet(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self.assertEqual(len(rec.line_ids), 3,
                         "실적을 만들면 시트 항목이 그대로 복사돼야 한다")
        self.assertTrue(rec.name.startswith("CK-"), rec.name)
        line = rec.line_ids.filtered(lambda l: l.item_name == "재생재 배합비율")
        self.assertEqual((line.spec_min, line.spec_max), (0.0, 20.0),
                         "기준 상하한도 함께 복사돼야 한다")
        self.assertEqual(rec.overall_result, "pending",
                         "판정 전에는 '양호' 가 아니라 '미완료' 다")

    def test_normal_record_is_ok_and_counted(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self._fill(rec, {"칼날 마모·파손": {"result": "ok"},
                         "스크린 눈막힘": {"result": "ok"},
                         "재생재 배합비율": {"value": 15.0}})
        self.assertEqual(rec.overall_result, "ok")
        rec.action_done()
        self.assertEqual(rec.state, "done")
        self.sheet.invalidate_recordset()
        self.assertEqual(self.sheet.last_record_date, self.today)
        self.assertEqual(self.sheet.next_due, self.today + timedelta(days=1))
        self.assertFalse(self.sheet.is_overdue)

    def test_record_lines_snapshot_survive_item_change(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        item = self.sheet.item_ids.filtered(lambda i: i.name == "재생재 배합비율")
        item.spec_max = 30.0
        line = rec.line_ids.filtered(lambda l: l.item_name == "재생재 배합비율")
        self.assertEqual(line.spec_max, 20.0,
                         "기준을 바꿔도 이미 만든 실적의 판정 근거는 그대로여야 한다")

    def test_item_delete_keeps_record_line(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        line = rec.line_ids.filtered(lambda l: l.item_name == "스크린 눈막힘")
        self.sheet.item_ids.filtered(lambda i: i.name == "스크린 눈막힘").unlink()
        self.assertTrue(line.exists(), "기준 항목을 지워도 과거 실적은 남아야 한다")
        self.assertFalse(line.item_id)

    # ── ② 기한 경과(overdue) 판정 ─────────────────────────────────────

    def test_never_executed_sheet_becomes_overdue(self):
        """한 번도 점검하지 않은 시트도 미실시로 잡혀야 한다."""
        sheet = self.Sheet.create({
            "name": "소화기 점검", "target_type": "facility", "cycle": "monthly",
            "start_date": self.today - timedelta(days=40),
        })
        self.assertFalse(sheet.last_record_date)
        self.assertEqual(sheet.next_due, self.today - timedelta(days=10))
        self.assertTrue(sheet.is_overdue,
                        "실적이 하나도 없는데 주기가 지났으면 미실시다")
        self.assertIn(sheet, self.Sheet.search([("is_overdue", "=", True)]))

    def test_overdue_after_cycle_elapsed(self):
        rec = self.Record.create({
            "sheet_id": self.sheet.id, "check_date": self.today - timedelta(days=5)})
        self._fill(rec, {"칼날 마모·파손": {"result": "ok"},
                         "스크린 눈막힘": {"result": "ok"},
                         "재생재 배합비율": {"value": 10.0}})
        rec.action_done()
        self.sheet.invalidate_recordset()
        self.assertEqual(self.sheet.next_due, self.today - timedelta(days=4))
        self.assertTrue(self.sheet.is_overdue)

    def test_draft_record_is_not_actual(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self._fill(rec, {"칼날 마모·파손": {"result": "ok"},
                         "스크린 눈막힘": {"result": "ok"},
                         "재생재 배합비율": {"value": 10.0}})
        self.sheet.invalidate_recordset()
        self.assertFalse(self.sheet.last_record_date,
                         "작성 중인 점검표는 실적이 아니다")
        rec.action_done()
        self.sheet.invalidate_recordset()
        self.assertEqual(self.sheet.last_record_date, self.today)
        rec.action_draft()
        self.sheet.invalidate_recordset()
        self.assertFalse(self.sheet.last_record_date,
                         "완료를 취소하면 실적에서도 빠져야 한다")

    def test_event_cycle_has_no_due(self):
        sheet = self.Sheet.create({
            "name": "금형 교환 시 점검", "target_type": "etc", "cycle": "event",
            "start_date": self.today - timedelta(days=365)})
        self.assertFalse(sheet.next_due, "'발생시' 는 기한 판정을 하지 않는다")
        self.assertFalse(sheet.is_overdue)

    def test_no_start_date_means_no_judgement(self):
        sheet = self.Sheet.create({
            "name": "미정 점검", "target_type": "etc", "cycle": "daily",
            "start_date": False})
        self.assertFalse(sheet.next_due)
        self.assertFalse(sheet.is_overdue)

    def test_overdue_search_matches_compute(self):
        all_sheets = self.Sheet.search([])
        computed = all_sheets.filtered(lambda s: s.is_overdue)
        searched = self.Sheet.search([("is_overdue", "=", True)])
        self.assertEqual(set(computed.ids), set(searched.ids))
        negated = self.Sheet.search([("is_overdue", "!=", True)])
        self.assertEqual(set(searched.ids) | set(negated.ids), set(all_sheets.ids))
        self.assertFalse(set(searched.ids) & set(negated.ids))

    def test_future_check_date_rejected(self):
        """미래 날짜로 점검을 기록해 미실시를 감추는 경로를 막는다."""
        with self.assertRaises(ValidationError):
            self.Record.create({"sheet_id": self.sheet.id,
                                "check_date": self.today + timedelta(days=1)})
        rec = self.Record.create({"sheet_id": self.sheet.id})
        with self.assertRaises(ValidationError):
            rec.check_date = self.today + timedelta(days=30)

    def test_switching_sheet_replaces_lines(self):
        other = self.Sheet.create({
            "name": "배합기 #1 일상점검", "target_type": "facility", "cycle": "daily",
            "item_ids": [(0, 0, {"name": "배합시간", "check_method": "measure",
                                 "spec_min": 60.0, "spec_max": 120.0, "uom_name": "초"})]})
        rec = self.Record.new({"sheet_id": self.sheet.id})
        rec._onchange_sheet_id()
        self.assertEqual(len(rec.line_ids), 3)
        rec.sheet_id = other
        rec._onchange_sheet_id()
        self.assertEqual(rec.line_ids.mapped("item_name"), ["배합시간"],
                         "시트를 바꾸면 이전 시트 항목이 남아 있으면 안 된다")

    def test_inactive_item_not_copied(self):
        self.sheet.item_ids.filtered(lambda i: i.name == "스크린 눈막힘").active = False
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self.assertEqual(len(rec.line_ids), 2,
                         "보관 처리한 기준 항목은 새 실적에 들어가지 않는다")

    def test_overdue_search_rejects_bad_operator(self):
        with self.assertRaises(ValidationError):
            self.Sheet.search([("is_overdue", ">", True)])

    # ── ③ 상·하한 벗어난 값의 합부 판정 ───────────────────────────────

    def test_value_out_of_spec_is_auto_ng(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        line = rec.line_ids.filtered(lambda l: l.item_name == "재생재 배합비율")
        line.value = 25.0
        self.assertEqual(line.result, "ng", "상한 20% 를 넘으면 자동 불량이다")
        self._fill(rec, {"칼날 마모·파손": {"result": "ok"}, "스크린 눈막힘": {"result": "ok"}})
        self.assertEqual(rec.overall_result, "issue")
        self.assertEqual(rec.ng_count, 1)

    def test_boundary_value_is_pass(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        line = rec.line_ids.filtered(lambda l: l.item_name == "재생재 배합비율")
        line.value = 20.0
        self.assertEqual(line.result, "ok", "경계값은 적합이다")

    def test_two_sided_spec_low_side(self):
        sheet = self.Sheet.create({
            "name": "냉각수 온도 F-PROOF", "target_type": "facility", "cycle": "daily",
            "item_ids": [(0, 0, {"name": "냉각수 온도", "check_method": "measure",
                                 "spec_min": 15.0, "spec_max": 25.0, "uom_name": "℃"})]})
        rec = self.Record.create({"sheet_id": sheet.id})
        rec.line_ids.value = 12.0
        self.assertEqual(rec.line_ids.result, "ng", "하한 미달도 불량이다")
        rec.line_ids.value = 20.0
        self.assertEqual(rec.line_ids.result, "ok")

    def test_spec_judgement_cannot_be_overridden(self):
        """기준 밖 값에 '양호' 를 적어 넣는 경로 = 허위기재. 서버에서 막아야 한다."""
        rec = self.Record.create({"sheet_id": self.sheet.id})
        line = rec.line_ids.filtered(lambda l: l.item_name == "재생재 배합비율")
        line.value = 25.0
        with self.assertRaises(ValidationError):
            line.result = "ok"
        with self.assertRaises(ValidationError):
            line.write({"value": 40.0, "result": "ok"})
        with self.assertRaises(ValidationError):
            line.result = "na"

    def test_spec_override_blocked_at_create(self):
        with self.assertRaises(ValidationError):
            self.Record.create({
                "sheet_id": self.sheet.id,
                "line_ids": [(0, 0, {"item_name": "임의", "spec_max": 10.0,
                                     "value": 99.0, "result": "ok"})]})

    def test_zero_value_is_not_measured(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        line = rec.line_ids.filtered(lambda l: l.item_name == "재생재 배합비율")
        self.assertEqual(line.judge_value(), "no_value")
        self.assertFalse(line.result, "미기입은 불량이 아니다")
        self.assertEqual(rec.overall_result, "pending")

    def test_qualitative_item_is_manual(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        line = rec.line_ids.filtered(lambda l: l.item_name == "칼날 마모·파손")
        self.assertEqual(line.judge_value(), "no_spec")
        line.result = "ng"
        self.assertEqual(line.result, "ng", "기준 없는 항목은 사람 판정을 지켜야 한다")

    def test_inverted_spec_rejected(self):
        with self.assertRaises(ValidationError):
            self.Sheet.create({
                "name": "역전 기준", "target_type": "etc", "cycle": "daily",
                "item_ids": [(0, 0, {"name": "x", "spec_min": 30.0, "spec_max": 10.0})]})

    # ── 빈 점검표 / 증빙 보호 ─────────────────────────────────────────

    def test_empty_record_cannot_be_done(self):
        sheet = self.Sheet.create({"name": "항목 없는 시트", "target_type": "etc",
                                   "cycle": "daily"})
        rec = self.Record.create({"sheet_id": sheet.id})
        self.assertEqual(rec.overall_result, "pending",
                         "항목이 없는 점검표는 '양호' 가 아니다")
        with self.assertRaises(UserError):
            rec.action_done()
        self.assertEqual(rec.state, "draft")

    def test_unjudged_line_blocks_done(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self._fill(rec, {"칼날 마모·파손": {"result": "ok"},
                         "재생재 배합비율": {"value": 10.0}})
        with self.assertRaises(UserError):
            rec.action_done()

    def test_sheet_delete_blocked_while_record_exists(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self.assertTrue(rec)
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.sheet.unlink()

    def test_duplicate_code_rejected(self):
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.Sheet.create({"name": "중복", "code": "CS-CRUSH-01",
                                   "target_type": "etc", "cycle": "daily"})


@tagged("post_install", "-at_install")
class TestCheckSheetFrame(TransactionCase):
    """양식 프레임 — 항목 정의(단위·기준방식·주기)를 화면에서 고칠 수 있게 한 부분.

    여기서 지키려는 것은 두 가지다.
      1. 회사 양식 표기를 그대로 담을 수 있는가 (40℃±10℃, 0.4~0.6Mpa, 항목별 주기)
      2. 기준을 고쳐도 **이미 판정된 실적이 흔들리지 않는가**
    2번이 무너지면 과거 판정을 소급 변조하는 시스템이 된다.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Sheet = cls.env["iatf.check.sheet"]
        cls.Record = cls.env["iatf.check.record"]
        cls.today = fields.Date.context_today(cls.Sheet)

        # 회사 '24년도 설비 일상점검표(사출) 를 그대로 옮긴 형태
        cls.sheet = cls.Sheet.create({
            "name": "사출 1호기 일상점검",
            "code": "CS-INJ-01",
            "target_type": "facility",
            "cycle": "daily",
            "start_date": cls.today,
            "item_ids": [
                (0, 0, {"name": "작동유 온도", "check_method": "measure",
                        "entry_type": "numeric", "spec_mode": "target",
                        "target_value": 40.0, "tolerance": 10.0, "uom_name": "℃",
                        "is_key_item": True}),
                (0, 0, {"name": "안전문 동작", "check_method": "function",
                        "standard": "안전도어 이상 없을 것"}),
            ],
        })
        cls.oil = cls.sheet.item_ids.filtered(lambda i: i.name == "작동유 온도")
        cls.door = cls.sheet.item_ids.filtered(lambda i: i.name == "안전문 동작")

    def _line(self, record, name):
        return record.line_ids.filtered(lambda l: l.item_name == name)

    # ── ① 정상 기록 생성 ──
    def test_target_tolerance_becomes_bounds(self):
        """40℃±10℃ 로 적으면 판정은 30~50 으로 돈다."""
        self.assertEqual(self.oil.spec_min, 30.0)
        self.assertEqual(self.oil.spec_max, 50.0)

    def test_record_carries_definition_snapshot(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        line = self._line(rec, "작동유 온도")
        self.assertEqual(line.spec_mode, "target")
        self.assertEqual(line.target_value, 40.0)
        self.assertEqual(line.uom_name, "℃")
        self.assertTrue(line.is_key_item)
        self.assertEqual(rec.sheet_revision, self.sheet.revision)

    # ── ② 기한 경과 판정 (항목별 주기) ──
    def test_item_cycle_overrides_sheet_cycle(self):
        """시트는 '일' 인데 항목만 '월' 이면 그 항목은 한 달 뒤에 걸린다."""
        self.door.cycle = "monthly"
        self.door.invalidate_recordset()
        self.assertEqual(self.door.next_due, self.today + timedelta(days=30))
        self.assertEqual(self.oil.next_due, self.today + timedelta(days=1))

    def test_item_overdue_is_counted(self):
        self.sheet.start_date = self.today - timedelta(days=5)
        self.sheet.item_ids.invalidate_recordset()
        self.assertTrue(self.oil.is_overdue)
        self.assertEqual(self.sheet.overdue_item_count, len(self.sheet.item_ids))

    # ── ③ 상하한 벗어난 값의 합부 판정 ──
    def test_value_outside_tolerance_is_ng(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self._line(rec, "작동유 온도").value = 55.0
        self.assertEqual(self._line(rec, "작동유 온도").result, "ng")

    def test_value_inside_tolerance_is_ok(self):
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self._line(rec, "작동유 온도").value = 47.0
        self.assertEqual(self._line(rec, "작동유 온도").result, "ok")

    # ── 개정해도 과거 판정이 흔들리지 않는가 (핵심) ──
    def test_revision_does_not_rewrite_past_judgement(self):
        """기준을 좁혀도 이미 '양호' 로 판정된 실적은 그대로여야 한다.

        47℃ 는 40±10 에서 합격이다. 나중에 기준을 40±5 로 좁히면 지금 기준으로는
        불합격이지만, 그때 판정은 그때 기준으로 남아야 한다. 여기가 무너지면
        심사에서 '이 값이 왜 합격이었나' 에 답할 수 없다.
        """
        rec = self.Record.create({"sheet_id": self.sheet.id})
        self._line(rec, "작동유 온도").value = 47.0
        self._line(rec, "안전문 동작").result = "ok"
        rec.action_done()
        before_rev = rec.sheet_revision

        self.oil.tolerance = 5.0  # 기준을 좁힌다
        self.assertEqual(self.oil.spec_max, 45.0)

        line = self._line(rec, "작동유 온도")
        line.invalidate_recordset()
        self.assertEqual(line.spec_max, 50.0, "실적의 기준 스냅샷이 개정에 끌려갔다")
        self.assertEqual(line.result, "ok", "과거 판정이 소급해서 바뀌었다")
        self.assertEqual(rec.sheet_revision, before_rev)
        self.assertGreater(self.sheet.revision, before_rev, "개정 차수가 안 올라갔다")

    def test_revision_log_records_what_changed(self):
        before = self.sheet.revision
        self.oil.write({"tolerance": 7.0})
        self.assertGreater(self.sheet.revision, before)
        latest = self.sheet.revision_ids[0]
        self.assertEqual(latest.revision, self.sheet.revision)
        self.assertIn("작동유 온도", latest.summary)

    def test_revision_log_is_not_editable(self):
        """이력을 고칠 수 있으면 이력이 아니다.

        관리자(superuser)로는 ACL 이 통과해 버려 확인이 되지 않는다. 실제로 이 화면을
        쓰는 사람 — 작업환경 관리자 권한 사용자 — 로 시도해야 의미가 있다.
        """
        self.oil.tolerance = 8.0
        log = self.sheet.revision_ids[0]
        manager = self.env["res.users"].create({
            "name": "점검 관리자", "login": "frame_mgr_test",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("iatf_work_environment.group_work_environment_manager").id,
            ])],
        })
        as_manager = log.with_user(manager)
        self.assertTrue(as_manager.summary, "관리자가 이력을 읽지도 못하면 증빙이 되지 않는다")
        with self.assertRaises(AccessError):
            as_manager.write({"summary": "손댐"})
        with self.assertRaises(AccessError):
            as_manager.unlink()

    # ── 조용히 망가지는 경로 ──
    def test_bounds_without_mode_are_not_ignored(self):
        """상·하한만 주고 방식을 안 주면 '범위' 로 잡아야 한다.

        기본값(정성)으로 두면 기준이 화면에 보이는데 판정에는 안 쓰인다.
        기준이 없는 것보다 나쁘다 — 담당자는 걸려 있다고 믿기 때문이다.
        """
        item = self.env["iatf.check.sheet.item"].create({
            "sheet_id": self.sheet.id, "name": "메인 AIR 압력",
            "spec_min": 0.4, "spec_max": 0.6, "uom_name": "Mpa",
        })
        self.assertEqual(item.spec_mode, "range")
        self.assertEqual(item.entry_type, "numeric")

    def test_qualitative_item_rejects_bounds(self):
        with self.assertRaises(ValidationError):
            self.door.write({"spec_min": 1.0})

    def test_numeric_spec_requires_numeric_entry(self):
        """수치 기준을 걸고 입력은 양호·불량만 받는 항목을 막는다."""
        with self.assertRaises(ValidationError):
            self.oil.write({"entry_type": "judge"})

    def test_min_mode_rejects_upper_bound(self):
        with self.assertRaises(ValidationError):
            self.env["iatf.check.sheet.item"].create({
                "sheet_id": self.sheet.id, "name": "그리스 잔량",
                "spec_mode": "min", "entry_type": "numeric",
                "spec_min": 10.0, "spec_max": 90.0,
            })
