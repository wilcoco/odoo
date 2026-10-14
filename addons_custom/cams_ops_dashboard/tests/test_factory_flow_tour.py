"""[R136] 4단 캐스케이드 UI web_tour — 회사 전체 → 생산 → 사출 계획 → 문서 폼 (테스트 세션, 미실행: 슬롯 배정 후).

서버 시험(test_factory_flow.py)과 분리해 기록한다. 사출 계획 모듈이 없으면 명시 skip(통과로 세지 않음).
"""
from datetime import date, timedelta

from odoo.tests import HttpCase, tagged


@tagged("post_install", "-at_install", "r136_ui")
class TestFactoryFlowTour(HttpCase):

    def setUp(self):
        super().setUp()
        Run = self.env.get("injection.planning.run")
        if Run is None:
            self.skipTest("injection_planning 미설치 — 사출 계획 노드가 not_installed 라 4단 시나리오를 돌릴 수 없다")
        day = date.today() + timedelta(days=15)
        # 어댑터 CO.PROD.INJ_PLAN 의 domain(회사 범위·plan_date_from) 에 들어오는 문서 1건
        self.run = Run.create({"plan_date_from": day, "plan_date_to": day})
        self.assertTrue(self.run.exists())

    def test_four_level_cascade_click_through(self):
        self.start_tour("/odoo/action-cams_ops_dashboard.action_factory_flow", "cams_ops_dashboard_factory_flow_tour", login="admin")
