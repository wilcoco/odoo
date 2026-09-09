from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoldStandard(TransactionCase):
    """금형 관리기준 마스터 (SQ 4_1·4_2·4_6·4_7).

    ① 정상 기록 생성 — 기준을 채우면 '관리기준 수립' 이 선다
    ② 기한 경과 판정 — 세척 주기 대비 예정일 경과
    ③ 상·하한 벗어난 값의 합부 판정 — 온도 판정
    """

    def _mold(self, **vals):
        base = {"name": "T-금형", "mold_type": "injection"}
        base.update(vals)
        return self.env["iatf.mold"].create(base)

    # ───────── ① 정상 기록 생성 ─────────

    def test_standard_ready_when_all_filled(self):
        mold = self._mold(
            grade="a", check_cycle_days=1, clean_cycle_days=180,
            preheat_temp_min=60.0, preheat_temp_max=90.0,
            mold_temp_min=40.0, mold_temp_max=70.0,
        )
        self.assertTrue(mold.is_standard_ready, "기준을 다 채우면 수립 완료")
        self.assertFalse(mold.standard_missing, "미비 항목이 없어야 한다")

    def test_standard_missing_lists_gaps(self):
        """비어 있으면 무엇이 비었는지 이름으로 알려준다."""
        mold = self._mold(check_cycle_days=1)
        self.assertFalse(mold.is_standard_ready)
        self.assertIn("관리등급", mold.standard_missing)
        self.assertIn("세척 주기", mold.standard_missing)
        self.assertIn("예열 온도 상하한", mold.standard_missing)

        mold.write({
            "grade": "b", "clean_cycle_days": 240,
            "preheat_temp_min": 60.0, "preheat_temp_max": 90.0,
            "mold_temp_min": 40.0, "mold_temp_max": 70.0,
        })
        self.assertTrue(mold.is_standard_ready, "채우면 즉시 반영")

    def test_gauge_does_not_require_temp_spec(self):
        """지그·게이지는 예열 대상이 아니라 온도 기준이 없어도 미비가 아니다."""
        gauge = self._mold(mold_type="gauge", grade="c",
                           check_cycle_days=30, clean_cycle_days=365)
        self.assertTrue(gauge.is_standard_ready)
        self.assertNotIn("예열", gauge.standard_missing or "")

    # ───────── ② 기한 경과 판정 ─────────

    def test_clean_overdue(self):
        today = fields.Date.context_today(self.env["iatf.mold"])
        mold = self._mold(clean_cycle_days=30)

        # 세척 실적이 없으면 예정일 자체가 없다 → 경과도 아니다(판정 불가)
        self.assertFalse(mold.next_clean_due)
        self.assertFalse(mold.is_clean_overdue, "실적이 없으면 '경과' 로 단정하지 않는다")

        # 40일 전에 세척 완료 → 예정일(30일 주기)은 10일 전 → 경과
        self.env["iatf.mold.maintenance"].create({
            "mold_id": mold.id, "maintenance_type": "clean",
            "date": today - relativedelta(days=40), "state": "done",
        })
        mold.invalidate_recordset()
        self.assertEqual(mold.last_clean_date, today - relativedelta(days=40))
        self.assertEqual(mold.next_clean_due, today - relativedelta(days=10))
        self.assertTrue(mold.is_clean_overdue)

        # 검색 필터도 같은 결과를 내야 한다 (화면의 '세척 기한 경과' 목록)
        found = self.env["iatf.mold"].search([("is_clean_overdue", "=", True)])
        self.assertIn(mold, found)

        # 오늘 세척하면 해소된다
        self.env["iatf.mold.maintenance"].create({
            "mold_id": mold.id, "maintenance_type": "clean",
            "date": today, "state": "done",
        })
        mold.invalidate_recordset()
        self.assertEqual(mold.next_clean_due, today + relativedelta(days=30))
        self.assertFalse(mold.is_clean_overdue)
        self.assertNotIn(
            mold, self.env["iatf.mold"].search([("is_clean_overdue", "=", True)])
        )

    def test_clean_overdue_search_negation(self):
        """'!=' 검색도 정확해야 한다. 예정일이 없는 금형은 '경과 아님' 쪽에 든다."""
        today = fields.Date.context_today(self.env["iatf.mold"])
        overdue = self._mold(clean_cycle_days=30)
        self.env["iatf.mold.maintenance"].create({
            "mold_id": overdue.id, "maintenance_type": "clean",
            "date": today - relativedelta(days=40), "state": "done",
        })
        never = self._mold(clean_cycle_days=30)  # 세척 실적 없음 → 예정일 없음
        overdue.invalidate_recordset()

        not_overdue = self.env["iatf.mold"].search([("is_clean_overdue", "!=", True)])
        self.assertIn(never, not_overdue)
        self.assertNotIn(overdue, not_overdue)

    def test_planned_clean_is_not_actual(self):
        """계획(planned) 상태의 세척은 실적이 아니다 — 없는 이행을 만들지 않는다."""
        today = fields.Date.context_today(self.env["iatf.mold"])
        mold = self._mold(clean_cycle_days=30)
        self.env["iatf.mold.maintenance"].create({
            "mold_id": mold.id, "maintenance_type": "clean",
            "date": today, "state": "planned",
        })
        mold.invalidate_recordset()
        self.assertFalse(mold.last_clean_date, "완료되지 않은 세척은 실적으로 세지 않는다")

    def test_no_cycle_means_no_judgement(self):
        """주기 미설정(0)이면 기한 판정을 하지 않는다 — 매일 경과로 잡히면 안 된다."""
        today = fields.Date.context_today(self.env["iatf.mold"])
        mold = self._mold(clean_cycle_days=0)
        self.env["iatf.mold.maintenance"].create({
            "mold_id": mold.id, "maintenance_type": "clean",
            "date": today - relativedelta(days=999), "state": "done",
        })
        mold.invalidate_recordset()
        self.assertFalse(mold.next_clean_due)
        self.assertFalse(mold.is_clean_overdue)

    # ───────── ③ 상·하한 벗어난 값의 합부 판정 ─────────

    def test_temp_in_spec_judgement(self):
        mold = self._mold(preheat_temp_min=60.0, preheat_temp_max=90.0,
                          mold_temp_min=40.0, mold_temp_max=70.0)
        self.assertEqual(mold.check_temp_in_spec(75.0, "preheat"), "ok")
        self.assertEqual(mold.check_temp_in_spec(60.0, "preheat"), "ok", "하한값 자체는 합격")
        self.assertEqual(mold.check_temp_in_spec(90.0, "preheat"), "ok", "상한값 자체는 합격")
        self.assertEqual(mold.check_temp_in_spec(59.9, "preheat"), "ng", "하한 미달")
        self.assertEqual(mold.check_temp_in_spec(90.1, "preheat"), "ng", "상한 초과")
        self.assertEqual(mold.check_temp_in_spec(55.0, "mold"), "ok", "금형온도는 별도 기준")
        self.assertEqual(mold.check_temp_in_spec(75.0, "mold"), "ng")

    def test_no_spec_is_not_pass_and_not_fail(self):
        """기준이 없으면 'no_spec'. 0℃ 상하한으로 읽어 전부 NG 로 만들지 않는다."""
        mold = self._mold()
        self.assertEqual(mold.check_temp_in_spec(75.0, "preheat"), "no_spec")
        self.assertEqual(mold.check_temp_in_spec(0.0, "mold"), "no_spec")

    def test_one_sided_spec(self):
        """하한만 있으면 하한만 본다 (상한 0 을 '0℃ 초과 금지' 로 읽지 않는다)."""
        mold = self._mold(preheat_temp_min=60.0, preheat_temp_max=0.0)
        self.assertEqual(mold.check_temp_in_spec(1000.0, "preheat"), "ok")
        self.assertEqual(mold.check_temp_in_spec(59.0, "preheat"), "ng")
