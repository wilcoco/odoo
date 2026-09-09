from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoldCheck(TransactionCase):
    """금형 일상/정기 점검 (SQ 4_1).

    ① 정상 기록 생성 — 번호 채번, 라인, 종합 판정
    ② 기한 경과 판정 — 점검 주기 대비 예정일 경과
    ③ 상·하한 벗어난 측정값의 합부 판정 — 정량 항목 자동 판정
    """

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({
            "name": "T-점검금형", "mold_type": "injection", "check_cycle_days": 7,
        })
        self.Check = self.env["iatf.mold.check"]

    def _check(self, lines=None, **vals):
        base = {"mold_id": self.mold.id, "check_type": "daily"}
        base.update(vals)
        if lines is not None:
            base["line_ids"] = [(0, 0, l) for l in lines]
        return self.Check.create(base)

    # ───────── ① 정상 기록 생성 ─────────

    def test_create_numbers_and_overall(self):
        chk = self._check(lines=[
            {"item_name": "형면 이물", "standard": "이물 없을 것", "result": "ok"},
            {"item_name": "슬라이드 작동", "result": "ok"},
        ])
        self.assertTrue(chk.name.startswith("MC-"), "시퀀스로 번호가 붙는다")
        self.assertEqual(chk.state, "draft")
        self.assertEqual(chk.overall_result, "ok")
        self.assertEqual(chk.ng_count, 0)

        chk.action_done()
        self.assertEqual(chk.state, "done")
        self.mold.invalidate_recordset()
        self.assertEqual(self.mold.check_count, 1)
        self.assertIn(chk, self.mold.check_ids)

    def test_ng_line_makes_issue(self):
        chk = self._check(lines=[
            {"item_name": "형면 이물", "result": "ok"},
            {"item_name": "냉각수 누수", "result": "ng"},
        ])
        self.assertEqual(chk.overall_result, "issue")
        self.assertEqual(chk.ng_count, 1)
        chk.action_done()
        self.assertTrue(
            chk.message_ids.filtered(lambda m: "이상 항목" in (m.body or "")),
            "이상이 있으면 chatter 에 남긴다",
        )

    # ───────── 빈 점검표가 '양호' 로 집계되면 안 된다 ─────────

    def test_empty_check_is_not_ok(self):
        """항목이 하나도 없는 점검표는 '양호' 가 아니라 '미완료' 다.

        설비 일상점검(iatf.daily.check)은 라인이 없어도 '양호' 로 계산된다.
        그 결함을 복사해 오면 아무것도 점검하지 않은 빈 표가 실적이 된다.
        """
        chk = self._check(lines=[])
        self.assertEqual(chk.overall_result, "pending")
        with self.assertRaises(UserError, msg="빈 점검표는 완료할 수 없다"):
            chk.action_done()
        self.assertEqual(chk.state, "draft")

    def test_unjudged_line_blocks_done(self):
        """판정이 비어 있는 항목이 하나라도 있으면 완료 불가 (작성 일부 누락 방지)."""
        chk = self._check(lines=[
            {"item_name": "형면 이물", "result": "ok"},
            {"item_name": "이젝터 핀", "result": False},
        ])
        self.assertEqual(chk.overall_result, "pending")
        with self.assertRaises(UserError):
            chk.action_done()

        chk.line_ids.filtered(lambda l: not l.result).result = "na"
        self.assertEqual(chk.overall_result, "ok", "'해당없음' 도 판정이다")
        chk.action_done()
        self.assertEqual(chk.state, "done")

    # ───────── ② 기한 경과 판정 ─────────

    def test_check_overdue(self):
        today = fields.Date.context_today(self.mold)

        # 실적이 없으면 예정일도 없다 → 경과로 단정하지 않는다
        self.assertFalse(self.mold.next_check_due)
        self.assertFalse(self.mold.is_check_overdue)

        # 10일 전 완료 점검 + 7일 주기 → 예정일은 3일 전 → 경과
        chk = self._check(check_date=today - relativedelta(days=10),
                          lines=[{"item_name": "형면 이물", "result": "ok"}])
        chk.action_done()
        self.mold.invalidate_recordset()
        self.assertEqual(self.mold.last_check_date, today - relativedelta(days=10))
        self.assertEqual(self.mold.next_check_due, today - relativedelta(days=3))
        self.assertTrue(self.mold.is_check_overdue)
        self.assertIn(
            self.mold, self.env["iatf.mold"].search([("is_check_overdue", "=", True)])
        )

        # 오늘 점검하면 해소된다
        chk2 = self._check(check_date=today,
                           lines=[{"item_name": "형면 이물", "result": "ok"}])
        chk2.action_done()
        self.mold.invalidate_recordset()
        self.assertEqual(self.mold.next_check_due, today + relativedelta(days=7))
        self.assertFalse(self.mold.is_check_overdue)
        self.assertNotIn(
            self.mold, self.env["iatf.mold"].search([("is_check_overdue", "=", True)])
        )

    def test_draft_check_is_not_actual(self):
        """작성 중인 점검표는 실적이 아니다 — 없는 이행을 만들지 않는다."""
        today = fields.Date.context_today(self.mold)
        self._check(check_date=today, lines=[{"item_name": "형면 이물", "result": "ok"}])
        self.mold.invalidate_recordset()
        self.assertFalse(self.mold.last_check_date, "draft 는 실적으로 세지 않는다")

    def test_periodic_check_does_not_reset_daily_cycle(self):
        """정기 점검 한 건이 일상점검 누락을 가리면 안 된다."""
        today = fields.Date.context_today(self.mold)
        chk = self._check(check_type="periodic", check_date=today,
                          lines=[{"item_name": "분해 점검", "result": "ok"}])
        chk.action_done()
        self.mold.invalidate_recordset()
        self.assertFalse(self.mold.last_check_date,
                         "일상점검 주기는 일상점검 실적으로만 리셋된다")

    def test_no_cycle_means_no_judgement(self):
        """주기 미설정(0)이면 기한 판정을 하지 않는다."""
        today = fields.Date.context_today(self.mold)
        self.mold.check_cycle_days = 0
        chk = self._check(check_date=today - relativedelta(days=999),
                          lines=[{"item_name": "형면 이물", "result": "ok"}])
        chk.action_done()
        self.mold.invalidate_recordset()
        self.assertFalse(self.mold.next_check_due)
        self.assertFalse(self.mold.is_check_overdue)

    def test_check_overdue_search_negation(self):
        """'!=' 검색도 정확해야 한다. 예정일 없는 금형은 '경과 아님' 쪽."""
        today = fields.Date.context_today(self.mold)
        chk = self._check(check_date=today - relativedelta(days=30),
                          lines=[{"item_name": "형면 이물", "result": "ok"}])
        chk.action_done()
        never = self.env["iatf.mold"].create({"name": "T-점검없음", "check_cycle_days": 7})
        self.mold.invalidate_recordset()

        not_overdue = self.env["iatf.mold"].search([("is_check_overdue", "!=", True)])
        self.assertIn(never, not_overdue)
        self.assertNotIn(self.mold, not_overdue)

    # ───────── ③ 상·하한 벗어난 측정값의 합부 판정 ─────────

    def test_value_out_of_spec_is_auto_ng(self):
        chk = self._check(lines=[
            {"item_name": "냉각수 온도", "spec_min": 20.0, "spec_max": 30.0,
             "value": 35.0, "uom_name": "℃"},
        ])
        line = chk.line_ids
        self.assertEqual(line.judge_value(), "ng")
        self.assertEqual(line.result, "ng", "기준 밖 측정값은 자동으로 불량")
        self.assertEqual(chk.overall_result, "issue")

        line.value = 25.0
        self.assertEqual(line.result, "ok", "기준 안으로 고치면 양호로 바뀐다")
        self.assertEqual(chk.overall_result, "ok")

    def test_boundaries_are_pass(self):
        chk = self._check(lines=[
            {"item_name": "하한값", "spec_min": 20.0, "spec_max": 30.0, "value": 20.0},
            {"item_name": "상한값", "spec_min": 20.0, "spec_max": 30.0, "value": 30.0},
        ])
        self.assertEqual(set(chk.line_ids.mapped("result")), {"ok"},
                         "상·하한 값 자체는 합격")

    def test_spec_judgement_cannot_be_overridden(self):
        """기준 밖 측정값에 '양호' 를 적어 넣는 경로를 만들지 않는다.

        여기가 열려 있으면 허위기재(SQ 다수미흡 25%) 가 시스템 안에서 가능해진다.
        """
        chk = self._check(lines=[
            {"item_name": "냉각수 온도", "spec_min": 20.0, "spec_max": 30.0, "value": 35.0},
        ])
        line = chk.line_ids
        self.assertEqual(line.result, "ng")
        # 손으로 뒤집기 시도 — 계산 필드가 편집 가능하므로 write 자체는 시도된다.
        # 제약이 없으면 여기서 통과해 버린다.
        with self.assertRaises(ValidationError, msg="기준 밖 값에 '양호' 저장 불가"):
            with self.env.cr.savepoint():
                line.result = "ok"
        # 한 번의 write 로 값과 결과를 같이 넣는 우회도 막혀야 한다
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                line.write({"value": 40.0, "result": "ok"})
        line.invalidate_recordset()
        self.assertEqual(line.result, "ng")

    def test_no_spec_line_is_manual(self):
        """상·하한 없는 정성 항목은 사람이 고른 값을 유지한다."""
        chk = self._check(lines=[
            {"item_name": "이물 부착", "standard": "이물 없을 것", "result": "ng"},
        ])
        line = chk.line_ids
        self.assertEqual(line.judge_value(), "no_spec")
        self.assertEqual(line.result, "ng", "정성 판정이 자동 로직에 덮이면 안 된다")

    def test_zero_value_is_not_measured(self):
        """측정값 0 은 '미기입' 이다. 안 적은 칸을 하한 미달로 읽지 않는다."""
        chk = self._check(lines=[
            {"item_name": "냉각수 온도", "spec_min": 20.0, "spec_max": 30.0},
        ])
        line = chk.line_ids
        self.assertEqual(line.judge_value(), "no_value")
        self.assertFalse(line.result, "미기입은 불량이 아니라 미판정")
        self.assertEqual(chk.overall_result, "pending")

    def test_one_sided_spec(self):
        """상한만 있으면 상한만 본다 (하한 0 을 '0 미만 금지' 로 읽지 않는다)."""
        chk = self._check(lines=[
            {"item_name": "이물 크기", "spec_max": 5.0, "value": 0.1},
        ])
        self.assertEqual(chk.line_ids.result, "ok")
        chk.line_ids.value = 9.0
        self.assertEqual(chk.line_ids.result, "ng")

    def test_inverted_spec_rejected(self):
        with self.assertRaises(ValidationError, msg="하한 > 상한 은 저장 거부"):
            self._check(lines=[
                {"item_name": "뒤집힌 기준", "spec_min": 50.0, "spec_max": 10.0},
            ])

    def test_mold_delete_blocked_while_check_exists(self):
        """점검 기록이 달린 금형은 지워지지 않는다 — 증빙이 조용히 사라지면 안 된다."""
        chk = self._check(lines=[{"item_name": "형면 이물", "result": "ok"}])
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.mold.unlink()
        chk.unlink()
        self.mold.unlink()
