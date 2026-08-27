import json
from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEapproval(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.user_writer = Users.create({
            "name": "기안자", "login": "eap_writer", "email": "w@t.kr",
            "groups_id": [(4, cls.env.ref("base.group_user").id)],
        })
        cls.user_leader = Users.create({
            "name": "팀장", "login": "eap_leader", "email": "l@t.kr",
            "groups_id": [(4, cls.env.ref("base.group_user").id)],
        })
        cls.user_head = Users.create({
            "name": "본부장", "login": "eap_head", "email": "h@t.kr",
            "groups_id": [(4, cls.env.ref("base.group_user").id)],
        })
        cls.grade_leader = cls.env["escon.job.grade"].create(
            {"name": "테스트부장", "sequence": 10})
        cls.dept_parent = cls.env["hr.department"].create({"name": "테스트본부"})
        cls.dept = cls.env["hr.department"].create(
            {"name": "테스트팀", "parent_id": cls.dept_parent.id})
        cls.emp_writer = cls.env["hr.employee"].create({
            "name": "기안자", "user_id": cls.user_writer.id,
            "department_id": cls.dept.id,
        })
        cls.emp_leader = cls.env["hr.employee"].create({
            "name": "팀장", "user_id": cls.user_leader.id,
            "department_id": cls.dept.id, "job_grade_id": cls.grade_leader.id,
        })
        cls.emp_head = cls.env["hr.employee"].create({
            "name": "본부장", "user_id": cls.user_head.id,
            "department_id": cls.dept_parent.id,
        })
        cls.dept_parent.manager_id = cls.emp_head.id

    def _make_line(self, vals):
        template = self.env["iatf.approval.template"].create({
            "name": "T-%s" % vals.get("approver_mode"),
            "line_ids": [(0, 0, dict({"sequence": 10}, **vals))],
        })
        return template.line_ids

    def test_resolve_job_grade_in_department(self):
        """부서 내 직급자: 상신자 부서에서 해당 직급 직원을 찾는다 (본인 제외)."""
        line = self._make_line(
            {"approver_mode": "job_grade", "job_grade_id": self.grade_leader.id})
        self.assertEqual(line._resolve_user(self.user_writer), self.user_leader)
        # 해당 직급이 본인뿐이면 상위 부서로 올라가고, 없으면 빈 recordset
        self.assertFalse(line._resolve_user(self.user_leader))

    def test_resolve_job_grade_walks_up(self):
        """부서에 없으면 상위 부서에서 찾는다."""
        self.emp_leader.department_id = self.dept_parent.id
        line = self._make_line(
            {"approver_mode": "job_grade", "job_grade_id": self.grade_leader.id})
        self.assertEqual(line._resolve_user(self.user_writer), self.user_leader)

    def test_resolve_dept_manager(self):
        """지정 부서의 부서장."""
        line = self._make_line(
            {"approver_mode": "dept_manager", "department_id": self.dept_parent.id})
        self.assertEqual(line._resolve_user(self.user_writer), self.user_head)
        # 부서장 미지정이면 결정 불가
        self.dept_parent.manager_id = False
        self.assertFalse(line._resolve_user(self.user_writer))

    def test_dashboard_payload(self):
        """대시보드 페이로드: 키 존재 + JSON 직렬화 가능 + 결재 대기 반영."""
        request = self.env["iatf.approval.request"].create({
            "res_model": "res.partner",
            "res_id": self.env.ref("base.main_partner").id,
            "requester_id": self.user_writer.id,
            "line_ids": [(0, 0, {"sequence": 10, "user_id": self.user_leader.id})],
        })
        request.action_submit()

        data = self.env["escon.eapproval.dashboard"].with_user(
            self.user_leader).get_dashboard_data()
        for key in ("user", "kpi", "to_approve", "my_requests", "leaves",
                    "leave_balance", "pumui", "drill", "errors", "server_time"):
            self.assertIn(key, data)
        self.assertEqual(data["kpi"]["to_approve"], 1)
        self.assertEqual(data["to_approve"][0]["doc_model"], "res.partner")
        json.dumps(data)  # 직렬화 가능해야 한다

        data_writer = self.env["escon.eapproval.dashboard"].with_user(
            self.user_writer).get_dashboard_data()
        self.assertEqual(data_writer["kpi"]["my_in_progress"], 1)
        json.dumps(data_writer)


@tagged("post_install", "-at_install")
class TestAnnualLeave(TransactionCase):
    """에스콘 연차 규정 (입사일 기준, 첫해 월 1일 최대 11 / 1년 15 / 3년 이상 16, 미이월)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engine = cls.env["escon.annual.leave"]
        cls.leave_type = cls.env.ref("escon_eapproval.leave_type_annual")
        cls.Allocation = cls.env["hr.leave.allocation"]
        cls.today = date(2026, 8, 27)

    def _emp(self, name, hire):
        return self.env["hr.employee"].create(
            {"name": name, "eap_hire_date": hire})

    def _allocs(self, emp):
        return self.Allocation.search(
            [("employee_id", "=", emp.id),
             ("holiday_status_id", "=", self.leave_type.id)],
            order="date_from")

    def test_first_year_monthly(self):
        """입사 첫해: 경과 개월수만큼 발생, 최대 11일. 실행 멱등 + 개월 증가 반영."""
        emp = self._emp("첫해", date(2025, 11, 1))
        self.Engine.update_annual_allocations(employees=emp, today=date(2026, 1, 15))
        alloc = self._allocs(emp)
        self.assertEqual(len(alloc), 1)
        self.assertEqual(alloc.number_of_days, 2)  # 12/1, 1/1
        self.assertEqual(alloc.date_from, date(2025, 11, 1))
        self.assertEqual(alloc.date_to, date(2026, 10, 31))
        self.assertEqual(alloc.state, "validate")
        # 9개월 경과 시점 → 9일로 증가, 배정은 여전히 1건
        self.Engine.update_annual_allocations(employees=emp, today=self.today)
        self.Engine.update_annual_allocations(employees=emp, today=self.today)
        alloc = self._allocs(emp)
        self.assertEqual(len(alloc), 1)
        self.assertEqual(alloc.number_of_days, 9)
        # 11개월 상한
        self.Engine.update_annual_allocations(employees=emp, today=date(2026, 10, 30))
        self.assertEqual(self._allocs(emp).number_of_days, 11)

    def test_after_first_anniversary(self):
        """1년 후: 기념일에 15일, 유효기간은 다음 기념일 전날까지 (미이월)."""
        emp = self._emp("2년차", date(2024, 6, 15))
        self.Engine.update_annual_allocations(employees=emp, today=self.today)
        alloc = self._allocs(emp)
        self.assertEqual(len(alloc), 1)
        self.assertEqual(alloc.number_of_days, 15)
        self.assertEqual(alloc.date_from, date(2026, 6, 15))
        self.assertEqual(alloc.date_to, date(2027, 6, 14))

    def test_senior_16_days(self):
        """근속 3년 이상: 16일."""
        emp = self._emp("4년차", date(2023, 8, 27))
        self.Engine.update_annual_allocations(employees=emp, today=self.today)
        alloc = self._allocs(emp)
        self.assertEqual(alloc.number_of_days, 16)
        self.assertEqual(alloc.date_from, date(2026, 8, 27))

    def test_no_hire_date_skipped(self):
        emp = self.env["hr.employee"].create({"name": "입사일없음"})
        summary = self.Engine.update_annual_allocations(employees=emp, today=self.today)
        self.assertIn("입사일없음", summary["no_hire_date"])
        self.assertFalse(self._allocs(emp))

    def test_manual_increase_not_reduced(self):
        """관리자가 수동으로 늘린 배정 일수는 줄이지 않는다."""
        emp = self._emp("수동조정", date(2026, 2, 1))
        self.Engine.update_annual_allocations(employees=emp, today=self.today)
        alloc = self._allocs(emp)
        alloc.write({"number_of_days": 10})
        self.Engine.update_annual_allocations(employees=emp, today=self.today)
        self.assertEqual(self._allocs(emp).number_of_days, 10)


@tagged("post_install", "-at_install")
class TestApprovalsIntegration(TransactionCase):
    """Odoo Approvals 연동: 기본 유형 보관 + 우리 유형 활성 + 대시보드 합산."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.owner = Users.create({
            "name": "요청자", "login": "apr_owner", "email": "o@t.kr",
            "groups_id": [(4, cls.env.ref("base.group_user").id)],
        })
        cls.approver = Users.create({
            "name": "승인자", "login": "apr_approver", "email": "a@t.kr",
            "groups_id": [(4, cls.env.ref("base.group_user").id)],
        })

    def test_default_categories_archived(self):
        """설치/업그레이드 시 Odoo 기본 유형은 보관, 우리 유형은 활성."""
        self.env["escon.eapproval.setup"].apply_odoo_defaults()  # 멱등 재실행
        default = self.env.ref("approvals.approval_category_data_general_approval")
        self.assertFalse(default.active)
        for xmlid in ("category_general", "category_expense", "category_trip",
                      "category_car", "category_gate", "category_rfq"):
            category = self.env.ref("escon_eapproval.%s" % xmlid)
            self.assertTrue(category.active, xmlid)
        self.assertEqual(
            self.env.ref("escon_eapproval.category_rfq").approval_type, "purchase")
        root_menu = self.env.ref("approvals.approvals_menu_root")
        self.assertFalse(root_menu.active)

    def test_dashboard_includes_approvals(self):
        request = self.env["approval.request"].create({
            "name": "통합 테스트 일반결재",
            "category_id": self.env.ref("escon_eapproval.category_general").id,
            "request_owner_id": self.owner.id,
            "approver_ids": [(0, 0, {"user_id": self.approver.id})],
        })
        request.with_user(self.owner).action_confirm()
        self.assertEqual(request.request_status, "pending")

        Dashboard = self.env["escon.eapproval.dashboard"]
        data = Dashboard.with_user(self.approver).get_dashboard_data()
        rows = [r for r in data["to_approve"] if r["doc_model"] == "approval.request"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["doc_id"], request.id)
        self.assertEqual(rows[0]["doc_label"], "일반 결재")
        json.dumps(data)

        data_owner = Dashboard.with_user(self.owner).get_dashboard_data()
        self.assertGreaterEqual(data_owner["kpi"]["my_in_progress"], 1)
        mine = [r for r in data_owner["my_requests"]
                if r["doc_model"] == "approval.request" and r["doc_id"] == request.id]
        self.assertTrue(mine)
