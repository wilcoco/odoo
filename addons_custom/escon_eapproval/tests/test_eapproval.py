import json

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
