from odoo import fields
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestOpsDashboardScope(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.department_a = cls.env["hr.department"].create({"name": "대시보드 A"})
        cls.department_b = cls.env["hr.department"].create({"name": "대시보드 B"})
        cls.user = new_test_user(cls.env, login="ops-dashboard-user", groups="base.group_user")
        cls.manager = new_test_user(
            cls.env,
            login="ops-dashboard-manager",
            groups="base.group_user,cams_ops_process.group_ops_manager",
        )
        cls.env["hr.employee"].create({
            "name": "대시보드 사용자",
            "user_id": cls.user.id,
            "department_id": cls.department_a.id,
        })
        roles = {}
        tasks = {}
        today = fields.Date.today()
        for key, department in (("a", cls.department_a), ("b", cls.department_b)):
            roles[key] = cls.env["ops.role"].create({
                "name": f"대시보드 {key.upper()} 역할",
                "department_ids": [(6, 0, department.ids)],
            })
            definition = cls.env["ops.task.def"].create({
                "name": f"대시보드 {key.upper()} 업무",
                "role_id": roles[key].id,
                "periodicity": "adhoc",
                "requires_approval": False,
            })
            tasks[key] = cls.env["ops.task"].create({
                "task_def_id": definition.id,
                "period_key": f"dashboard-{key}",
                "scheduled_date": today,
                "due_date": today,
            })
        cls.roles = roles
        cls.tasks = tasks

    def test_internal_user_dashboard_keeps_department_scope(self):
        data = self.env["cams.ops.dashboard"].with_user(self.user).get_dashboard_data()
        self.assertEqual(data["counts"]["today"], 1)
        self.assertEqual([task["id"] for task in data["today_tasks"]], [self.tasks["a"].id])
        self.assertTrue(data["today_tasks"][0]["can_complete"])
        self.assertFalse(data["user"]["is_manager"])
        self.assertFalse(data["departments"])

    def test_manager_can_filter_dashboard_by_department(self):
        dashboard = self.env["cams.ops.dashboard"].with_user(self.manager)
        self.assertEqual(dashboard.get_dashboard_data()["counts"]["today"], 2)

        data = dashboard.get_dashboard_data(department_id=self.department_b.id)
        self.assertEqual(data["counts"]["today"], 1)
        self.assertEqual([task["id"] for task in data["today_tasks"]], [self.tasks["b"].id])
        self.assertEqual(data["selected_department_id"], self.department_b.id)

    def test_dashboard_menu_is_active_for_internal_users(self):
        menu = self.env.ref("cams_ops_dashboard.menu_cams_ops_dashboard")
        self.assertTrue(menu.active)
        self.assertEqual(menu.parent_id, self.env.ref("cams_ops_process.menu_ops_root"))
        self.assertEqual(menu.action, self.env.ref("cams_ops_dashboard.action_cams_ops_dashboard"))
        self.assertEqual(menu.groups_id, self.env.ref("base.group_user"))
        visible_ids = self.env["ir.ui.menu"].with_user(self.user)._visible_menu_ids()
        self.assertIn(menu.id, visible_ids)
