from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestSafety(TransactionCase):
    """SQ 사출 6_1 안전관리 — 위험성평가 / 아차사고·사고 / 안전점검 시트."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.context_today(cls.env["iatf.safety.assessment"])
        cls.Assess = cls.env["iatf.safety.assessment"]
        cls.Incident = cls.env["iatf.safety.incident"]
        cls.Sheet = cls.env["iatf.check.sheet"]
        cls.area = cls.env["iatf.work.area"].create({"name": "사출 1라인"})

    def _assessment(self, **kw):
        vals = {"title": "사출기 금형 교환 작업", "work_area_id": self.area.id}
        vals.update(kw)
        return self.Assess.create(vals)

    # ─────────────────────────────────────────────────────────
    # 1. 정상 기록 생성
    # ─────────────────────────────────────────────────────────
    def test_normal_assessment_is_created_and_completed(self):
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "금형 낙하", "hazard_type": "mechanical",
                    "likelihood": "2", "severity": "3",
                    "measure": "호이스트 슬링 점검 후 작업, 하부 출입 통제",
                    "action_state": "done", "done_date": self.today}),
            (0, 0, {"hazard": "협착", "likelihood": "1", "severity": "2"}),
        ])
        self.assertTrue(a.name.startswith("RA-"), a.name)
        self.assertEqual(a.line_count, 2)
        self.assertEqual(a.max_risk, 6)
        self.assertEqual(a.unacceptable_count, 1)
        self.assertEqual(a.open_action_count, 0)
        a.action_done()
        self.assertEqual(a.state, "done")

    def test_normal_incident_flows_to_closed(self):
        i = self.Incident.create({
            "title": "금형 교환 중 슬링 미끄러짐",
            "incident_type": "near_miss",
            "work_area_id": self.area.id,
            "description": "금형 인양 중 슬링이 모서리에서 미끄러졌으나 낙하 전 정지",
        })
        self.assertTrue(i.name.startswith("SI-"), i.name)
        self.assertEqual(i.state, "reported")
        i.action_analyze()
        i.cause = "모서리 보호대 미사용"
        i.action_start_action()
        self.assertEqual(i.state, "action")
        i.write({"countermeasure": "모서리 보호대 비치 및 작업표준 개정",
                 "done_date": self.today})
        i.action_close()
        self.assertEqual(i.state, "closed")

    def test_near_miss_lives_in_the_same_ledger(self):
        """아차사고와 재해가 한 원장에 있어야 '사고 0건' 뒤의 예방활동이 보인다."""
        self.Incident.create({"title": "n1", "incident_type": "near_miss",
                              "description": "x"})
        self.Incident.create({"title": "a1", "incident_type": "first_aid",
                              "description": "y"})
        self.assertEqual(self.Incident.search_count(
            [("incident_type", "in", ["near_miss", "first_aid"])]), 2)

    # ─────────────────────────────────────────────────────────
    # 2. 기한 경과 판정
    # ─────────────────────────────────────────────────────────
    def test_safety_sheet_overdue_uses_check_sheet_engine(self):
        """안전점검은 네 번째 원장이 아니라 점검 시트다. 미실시 판정도 그대로 동작한다."""
        s = self.Sheet.create({
            "name": "소화기 월간 점검", "target_type": "facility", "is_safety": True,
            "cycle": "monthly",
            "start_date": self.today - timedelta(days=40),
        })
        self.assertTrue(s.is_overdue)
        self.assertIn(s, self.Sheet.search([("is_safety", "=", True),
                                            ("is_overdue", "=", True)]))

    def test_safety_sheet_not_overdue_before_cycle(self):
        s = self.Sheet.create({
            "name": "비상구 주간 점검", "target_type": "facility", "is_safety": True,
            "cycle": "weekly", "start_date": self.today - timedelta(days=3),
        })
        self.assertFalse(s.is_overdue)

    def test_safety_sheet_action_only_shows_safety(self):
        safety = self.Sheet.create({"name": "방호장치 점검", "target_type": "facility",
                                    "is_safety": True, "cycle": "monthly"})
        normal = self.Sheet.create({"name": "분쇄기 일상점검", "target_type": "facility",
                                    "cycle": "daily"})
        act = self.env.ref("iatf_work_environment.action_safety_check_sheet")
        hits = self.Sheet.search(safe_eval(act.domain))
        self.assertIn(safety, hits)
        self.assertNotIn(normal, hits)

    def test_incident_overdue_filter_matches_reality(self):
        """뷰에 실린 '대책 기한 경과' 도메인을 그대로 평가해 검증한다."""
        late = self.Incident.create({
            "title": "대책 지연", "description": "x",
            "due_date": self.today - timedelta(days=5), "state": "action"})
        ontime = self.Incident.create({
            "title": "기한 내", "description": "y",
            "due_date": self.today + timedelta(days=5), "state": "action"})
        closed = self.Incident.create({
            "title": "종결됨", "description": "z", "cause": "c",
            "countermeasure": "m", "done_date": self.today,
            "due_date": self.today - timedelta(days=5), "state": "action"})
        closed.action_close()

        dom = self._view_filter_domain(
            "iatf_work_environment.view_safety_incident_search", "f_overdue")
        hits = self.Incident.search(dom)
        self.assertIn(late, hits)
        self.assertNotIn(ontime, hits)
        self.assertNotIn(closed, hits, "종결된 건은 기한 경과로 잡히면 안 된다")

    def test_action_due_date_does_not_freeze(self):
        """기한 판정은 오늘 기준이다. 저장 필드로 굳혀 두지 않았는지 확인한다."""
        i = self.Incident.create({"title": "t", "description": "d",
                                  "due_date": self.today + timedelta(days=1),
                                  "state": "action"})
        dom = self._view_filter_domain(
            "iatf_work_environment.view_safety_incident_search", "f_overdue")
        self.assertNotIn(i, self.Incident.search(dom))
        i.due_date = self.today - timedelta(days=1)
        self.assertIn(i, self.Incident.search(dom))

    # ─────────────────────────────────────────────────────────
    # 3. 상하한(임계) 판정 — 위험성 점수의 합부
    # ─────────────────────────────────────────────────────────
    def test_risk_score_below_threshold_is_acceptable(self):
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "미끄러짐", "likelihood": "1", "severity": "1"})])
        ln = a.line_ids
        self.assertEqual(ln.risk_score, 1)
        self.assertEqual(ln.risk_level, "low")
        self.assertTrue(ln.acceptable)

    def test_risk_score_boundary_three_is_acceptable(self):
        """3 은 허용 경계 안쪽. 4 부터 허용 불가."""
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "경계", "likelihood": "1", "severity": "3"})])
        self.assertEqual(a.line_ids.risk_score, 3)
        self.assertTrue(a.line_ids.acceptable)

    def test_risk_score_boundary_four_is_unacceptable(self):
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "경계", "likelihood": "2", "severity": "2"})])
        ln = a.line_ids
        self.assertEqual(ln.risk_score, 4)
        self.assertEqual(ln.risk_level, "medium")
        self.assertFalse(ln.acceptable)

    def test_risk_score_high_is_unacceptable(self):
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "감전", "likelihood": "3", "severity": "3"})])
        ln = a.line_ids
        self.assertEqual(ln.risk_score, 9)
        self.assertEqual(ln.risk_level, "high")
        self.assertFalse(ln.acceptable)

    def test_risk_recomputes_when_rated_again(self):
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "재평가", "likelihood": "3", "severity": "3"})])
        a.line_ids.likelihood = "1"
        self.assertEqual(a.line_ids.risk_score, 3)
        self.assertTrue(a.line_ids.acceptable)
        self.assertEqual(a.max_risk, 3)

    def test_after_risk_needs_both_ratings(self):
        """한쪽만 넣은 재평가는 재평가가 아니다. 0(미평가)으로 둔다."""
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "개선전", "likelihood": "3", "severity": "3",
                    "measure": "방호덮개", "after_likelihood": "1"})])
        ln = a.line_ids
        self.assertEqual(ln.after_risk_score, 0)
        ln.after_severity = "2"
        self.assertEqual(ln.after_risk_score, 2)

    # ─────────────────────────────────────────────────────────
    # 4. 허위·공백 기재 차단
    # ─────────────────────────────────────────────────────────
    def test_empty_assessment_cannot_be_done(self):
        a = self._assessment()
        with self.assertRaises(UserError):
            a.action_done()
        self.assertEqual(a.state, "draft")

    def test_unacceptable_without_measure_blocks_done(self):
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "협착", "likelihood": "3", "severity": "3"})])
        with self.assertRaises(UserError):
            a.action_done()
        a.line_ids.measure = "안전문 인터록 설치"
        a.action_done()
        self.assertEqual(a.state, "done")

    def test_action_done_requires_measure_and_date(self):
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "낙하", "likelihood": "2", "severity": "3"})])
        ln = a.line_ids
        with self.assertRaises(ValidationError):
            ln.write({"action_state": "done"})
        ln.write({"measure": "슬링 교체"})
        with self.assertRaises(ValidationError):
            ln.write({"action_state": "done"})
        ln.write({"action_state": "done", "done_date": self.today})
        self.assertEqual(ln.action_state, "done")

    def test_future_dates_rejected(self):
        tomorrow = self.today + timedelta(days=1)
        with self.assertRaises(ValidationError):
            self._assessment(assess_date=tomorrow)
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "h", "measure": "m", "likelihood": "1", "severity": "1"})])
        with self.assertRaises(ValidationError):
            a.line_ids.write({"action_state": "done", "done_date": tomorrow})
        with self.assertRaises(ValidationError):
            self.Incident.create({
                "title": "미래 사고", "description": "d",
                "occurred_at": fields.Datetime.now() + timedelta(days=1)})

    def test_incident_cannot_close_without_cause_and_countermeasure(self):
        i = self.Incident.create({"title": "무근본원인 종결", "description": "d",
                                  "state": "action"})
        with self.assertRaises(UserError):
            i.action_close()
        i.cause = "c"
        with self.assertRaises(UserError):
            i.action_close()
        i.countermeasure = "m"
        with self.assertRaises(UserError):
            i.action_close()
        i.done_date = self.today
        i.action_close()
        self.assertEqual(i.state, "closed")

    def test_state_write_cannot_bypass_done_guard(self):
        """버튼을 우회해 state 만 바꾸는 경로를 막았는지 확인한다."""
        empty = self._assessment()
        with self.assertRaises(ValidationError):
            empty.write({"state": "done"})
        risky = self._assessment(line_ids=[
            (0, 0, {"hazard": "협착", "likelihood": "3", "severity": "3"})])
        with self.assertRaises(ValidationError):
            risky.write({"state": "done"})

    def test_state_write_cannot_bypass_close_guard(self):
        i = self.Incident.create({"title": "t", "description": "d"})
        with self.assertRaises(ValidationError):
            i.write({"state": "closed"})

    def test_completed_assessment_cannot_be_gutted(self):
        """완료 후 대책을 지우거나 등급을 올려 내용을 비우는 경로도 막힌다."""
        a = self._assessment(line_ids=[
            (0, 0, {"hazard": "협착", "likelihood": "3", "severity": "3",
                    "measure": "인터록 설치"})])
        a.action_done()
        with self.assertRaises(ValidationError):
            a.line_ids.write({"measure": False})
        with self.assertRaises(ValidationError):
            a.line_ids.unlink()
        self.assertEqual(a.line_ids.measure, "인터록 설치")

    def test_incident_cannot_skip_cause_analysis(self):
        i = self.Incident.create({"title": "t", "description": "d"})
        i.action_analyze()
        with self.assertRaises(UserError):
            i.action_start_action()
        self.assertEqual(i.state, "analyzing")

    def test_equipment_link_survives_equipment_delete(self):
        """설비를 지워도 사고 이력은 남아야 한다. 증빙이 사라지면 안 된다."""
        eq = self.env["iatf.equipment"].create({"name": "ADV 분쇄기"})
        i = self.Incident.create({"title": "t", "description": "d",
                                  "equipment_id": eq.id})
        eq.unlink()
        i.invalidate_recordset()
        self.assertTrue(i.exists())
        self.assertFalse(i.equipment_id)

    def test_no_demo_records_shipped(self):
        """실적을 데모로 채우지 않는다 — 허위기재는 다수미흡(25%) 사유다."""
        self.assertEqual(self.Assess.search_count([("name", "like", "RA-")]),
                         self.Assess.search_count([]))
        for model in ("iatf.safety.assessment", "iatf.safety.incident"):
            demo = self.env["ir.model.data"].search_count([
                ("model", "=", model)])
            self.assertEqual(demo, 0, "%s 에 XML 데이터가 실려 있다" % model)

    # ── helper ──
    def _view_filter_domain(self, xmlid, filter_name):
        from lxml import etree
        arch = etree.fromstring(self.env.ref(xmlid).arch)
        node = arch.xpath("//filter[@name='%s']" % filter_name)
        self.assertTrue(node, "필터 %s 가 뷰에 없다" % filter_name)
        return safe_eval(node[0].get("domain"), self._domain_eval_ctx())

    def _domain_eval_ctx(self):
        # safe_eval 은 날것의 모듈을 거부한다. 웹 클라이언트가 검색 도메인을 평가할 때
        # 쓰는 것과 같은 래핑된 모듈을 넘겨야 실제 동작과 같은 조건에서 검증된다.
        from dateutil.relativedelta import relativedelta
        from odoo.tools import safe_eval as _se
        return {
            "context_today": lambda: self.today,
            "datetime": _se.datetime,
            "time": _se.time,
            "relativedelta": relativedelta,
            "uid": self.env.uid,
        }
