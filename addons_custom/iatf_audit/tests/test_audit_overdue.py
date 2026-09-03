from datetime import timedelta

from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import fields
from odoo.tests import TransactionCase, tagged
from odoo.tools import safe_eval as _se
from odoo.tools.safe_eval import safe_eval


@tagged("post_install", "-at_install")
class TestAuditOverdue(TransactionCase):
    """내부심사 계획 대비 실적 — SQ 6_4.

    계획일이 지났는데 실시하지 않은 심사를 찾아내는 것이 핵심이다. 판정을 저장
    필드로 두면 값이 굳으므로, 뷰 도메인(오늘 기준)으로 처리했다. 그래서 테스트도
    **뷰에 실제로 실려 있는 도메인 문자열**을 평가해서 확인한다.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Audit = cls.env["iatf.audit"]
        cls.today = fields.Date.context_today(cls.Audit)

    def _audit(self, **kw):
        vals = {"title": "공정심사", "planned_date": self.today,
                "lead_auditor_id": self.env.user.id}
        vals.update(kw)
        return self.Audit.create(vals)

    def _filter_domain(self, name):
        arch = etree.fromstring(
            self.env.ref("iatf_audit.view_iatf_audit_search").arch)
        node = arch.xpath("//filter[@name='%s']" % name)
        self.assertTrue(node, "필터 %s 가 검색뷰에 없다" % name)
        # safe_eval 은 날것의 모듈을 거부한다. 웹 클라이언트와 같은 래핑 모듈을 넘긴다.
        return safe_eval(node[0].get("domain"), {
            "context_today": lambda: self.today,
            "datetime": _se.datetime,
            "time": _se.time,
            "relativedelta": relativedelta,
            "uid": self.env.uid,
        })

    # 1. 정상 기록 생성
    def test_planned_audit_is_created(self):
        a = self._audit()
        self.assertEqual(a.state, "planned")
        self.assertFalse(a.actual_date)

    def test_started_audit_records_actual_date(self):
        a = self._audit(planned_date=self.today - timedelta(days=1))
        a.action_start()
        self.assertEqual(a.state, "in_progress")
        self.assertEqual(a.actual_date, self.today)

    # 2. 기한 경과 판정
    def test_overdue_filter_catches_unexecuted_plan(self):
        late = self._audit(planned_date=self.today - timedelta(days=1))
        future = self._audit(planned_date=self.today + timedelta(days=7))
        on_today = self._audit(planned_date=self.today)

        hits = self.Audit.search(self._filter_domain("overdue"))
        self.assertIn(late, hits)
        self.assertNotIn(future, hits)
        self.assertNotIn(on_today, hits, "계획일 당일은 아직 경과가 아니다")

    def test_executed_audit_leaves_overdue_list(self):
        a = self._audit(planned_date=self.today - timedelta(days=3))
        self.assertIn(a, self.Audit.search(self._filter_domain("overdue")))
        a.action_start()
        self.assertNotIn(a, self.Audit.search(self._filter_domain("overdue")))

    def test_cancelled_audit_is_not_overdue(self):
        a = self._audit(planned_date=self.today - timedelta(days=3))
        a.action_cancel()
        self.assertNotIn(a, self.Audit.search(self._filter_domain("overdue")))

    def test_overdue_judgement_is_not_frozen(self):
        """오늘 기준으로 다시 계산되어야 한다. 저장했다면 여기서 걸린다."""
        a = self._audit(planned_date=self.today + timedelta(days=1))
        self.assertNotIn(a, self.Audit.search(self._filter_domain("overdue")))
        a.planned_date = self.today - timedelta(days=1)
        self.assertIn(a, self.Audit.search(self._filter_domain("overdue")))

    def test_no_actual_filter_catches_missing_evidence(self):
        """진행했다고 상태만 바꾸고 실적일이 빈 건을 잡는다."""
        a = self._audit()
        a.write({"state": "report"})
        self.assertIn(a, self.Audit.search(self._filter_domain("no_actual")))
        a.actual_date = self.today
        self.assertNotIn(a, self.Audit.search(self._filter_domain("no_actual")))

    # 3. 액션 배선
    def test_overdue_action_is_wired(self):
        act = self.env.ref("iatf_audit.action_iatf_audit_overdue")
        self.assertEqual(act.res_model, "iatf.audit")
        ctx = safe_eval(act.context)
        self.assertEqual(ctx.get("search_default_overdue"), 1)

    def test_no_demo_audits_shipped(self):
        self.assertEqual(
            self.env["ir.model.data"].search_count([("model", "=", "iatf.audit")]), 0)
