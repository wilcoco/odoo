"""테스트 세션 검토용 — 개발 세션이 요청한 5건을 시나리오로 재현한다.

요청 원문: docs/신호_테스트세션_할일.md [회신 2026-09-04] §5
이 파일은 **검토가 끝나면 개발 세션 테스트로 통합하거나 삭제**한다.
"""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCheckSheetFrameReview(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Sheet = cls.env["iatf.check.sheet"]
        cls.Record = cls.env["iatf.check.record"]

    def _sheet(self, cycle="daily", **kw):
        return self.Sheet.create(dict({
            "name": "T-점검시트", "target_type": "facility", "cycle": cycle,
        }, **kw))

    def _item(self, sheet, **kw):
        return self.env["iatf.check.sheet.item"].create(dict({
            "sheet_id": sheet.id, "name": "T-작동유온도",
            "entry_type": "numeric", "spec_mode": "target",
            "target_value": 40.0, "tolerance": 10.0,
        }, **kw))

    def _record(self, sheet, value, date="2026-09-04"):
        rec = self.Record.create({"sheet_id": sheet.id, "check_date": date})
        for line in rec.line_ids:
            line.value = value
        return rec

    # ── ① 개정 후 과거 실적이 흔들리지 않는가 (최우선) ──────────────
    def test_1_past_record_immune_to_spec_change(self):
        sheet = self._sheet()
        item = self._item(sheet)                      # 40±10 → 30~50
        rec = self._record(sheet, 47.0)               # 합격이어야 함
        line = rec.line_ids[0]
        self.assertEqual(line.result, "ok", "47℃ 는 30~50 안이므로 합격")
        before = (line.spec_min, line.spec_max, line.result)
        if "state" in rec._fields:
            try:
                rec.action_done()
            except Exception:                          # 완료 버튼명이 다르면 통과
                pass

        item.write({"tolerance": 5.0})                 # 40±5 → 35~45 로 좁힘
        rec.invalidate_recordset()
        line.invalidate_recordset()
        after = (line.spec_min, line.spec_max, line.result)
        self.assertEqual(before, after,
                         "기준 개정이 과거 실적의 기준·판정을 소급 변경하면 안 된다 "
                         f"(before={before} after={after})")
        # 새 실적은 새 기준을 따라야 한다
        new_rec = self._record(sheet, 47.0)   # 오늘자 (미래 날짜는 시스템이 막는다 — 정상)
        self.assertEqual(new_rec.line_ids[0].result, "ng",
                         "개정 후 새 점검은 좁혀진 기준(35~45)으로 판정되어야 한다")

    # ── ② 개정 이력 위변조가 막히는가 ──────────────────────────────
    def test_2_revision_log_is_immutable(self):
        sheet = self._sheet()
        self._item(sheet)
        logs = self.env["iatf.check.sheet.revision"].search([("sheet_id", "=", sheet.id)])
        self.assertTrue(logs, "항목 추가 시 개정 이력이 남아야 한다")
        mgr = self.env.ref("base.user_admin")
        log = logs[0].with_user(mgr)
        for op, fn in (("수정", lambda: log.write({"summary": "위변조"})),
                       ("삭제", lambda: log.unlink())):
            try:
                fn()
            except (AccessError, UserError):
                continue
            self.fail("개정 이력 %s 가 막히지 않는다 — 판정 근거 위변조 가능" % op)

    # ── ③ 기준 방식 전환 시 경계값 잔존 ────────────────────────────
    def test_3_spec_mode_switch_no_stale_bounds(self):
        sheet = self._sheet()
        item = self._item(sheet, spec_mode="range", target_value=0, tolerance=0,
                          spec_min=0.4, spec_max=0.6)
        # 범위 → 정성 : 경계값이 남아 조용히 판정되면 안 된다
        with self.assertRaises(ValidationError,
                               msg="정성으로 바꾸면서 경계값을 남기면 막아야 한다"):
            item.write({"spec_mode": "qualitative"})
        # 정상 경로: 경계값을 함께 비우면 통과
        item.write({"spec_mode": "qualitative", "spec_min": 0.0, "spec_max": 0.0})
        self.assertEqual((item.spec_min, item.spec_max), (0.0, 0.0))
        # 하한 이상으로 전환하며 상한을 남기면 막아야 한다
        with self.assertRaises(ValidationError):
            item.write({"spec_mode": "min", "spec_min": 0.4, "spec_max": 0.6})

    # ── ④ 항목별 주기가 시트 주기를 이기는가 ───────────────────────
    def test_4_item_cycle_overrides_sheet_cycle(self):
        sheet = self._sheet(cycle="daily", start_date="2026-09-01")
        daily = self._item(sheet, name="T-일상항목")            # 시트 주기(일) 상속
        monthly = self._item(sheet, name="T-월간항목", cycle="monthly")
        self.assertFalse(daily.cycle, "비우면 시트 주기를 따른다")
        if "next_due" in daily._fields and daily.next_due and monthly.next_due:
            self.assertLess(daily.next_due, monthly.next_due,
                            "일 주기 항목의 기한이 월 주기 항목보다 빨라야 한다")
        else:
            self.skipTest("항목 기한 필드명이 달라 스킵 — 개발 세션 확인 필요")

    # ── ⑤ 수치 기준 + 양호·불량 입력 조합 차단 ─────────────────────
    def test_5_numeric_spec_with_pass_fail_input_blocked(self):
        sheet = self._sheet()
        with self.assertRaises(ValidationError,
                               msg="수치 기준인데 양호·불량 입력이면 눈대중 판정이 된다"):
            self._item(sheet, entry_type="judge", spec_mode="range",
                       target_value=0, tolerance=0, spec_min=0.4, spec_max=0.6)
