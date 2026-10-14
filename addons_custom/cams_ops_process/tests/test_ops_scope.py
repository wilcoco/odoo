from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestOpsDepartmentScope(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ops_user_group = cls.env.ref("cams_ops_process.group_ops_user")
        cls.ops_manager_group = cls.env.ref("cams_ops_process.group_ops_manager")
        cls.department_a = cls.env["hr.department"].create({"name": "운영 A"})
        cls.department_b = cls.env["hr.department"].create({"name": "운영 B"})
        cls.user_a = new_test_user(cls.env, login="ops-a", groups="base.group_user")
        cls.user_b = new_test_user(cls.env, login="ops-b", groups="base.group_user")
        cls.manager = new_test_user(
            cls.env,
            login="ops-manager",
            groups="base.group_user,cams_ops_process.group_ops_manager",
        )
        cls.user_a.write({"groups_id": [(4, cls.ops_user_group.id)]})
        cls.user_b.write({"groups_id": [(4, cls.ops_user_group.id)]})
        cls.env["hr.employee"].create({
            "name": "운영 A 사용자",
            "user_id": cls.user_a.id,
            "department_id": cls.department_a.id,
        })
        cls.env["hr.employee"].create({
            "name": "운영 B 사용자",
            "user_id": cls.user_b.id,
            "department_id": cls.department_b.id,
        })
        cls.role_a = cls.env["ops.role"].create({
            "name": "A 역할",
            "department_ids": [(6, 0, cls.department_a.ids)],
        })
        cls.role_b = cls.env["ops.role"].create({
            "name": "B 역할",
            "department_ids": [(6, 0, cls.department_b.ids)],
        })
        cls.definition_a = cls.env["ops.task.def"].create({
            "name": "A 업무",
            "role_id": cls.role_a.id,
            "periodicity": "adhoc",
            "requires_approval": False,
        })
        cls.definition_b = cls.env["ops.task.def"].create({
            "name": "B 업무",
            "role_id": cls.role_b.id,
            "periodicity": "adhoc",
            "requires_approval": True,
            "approver_role_id": cls.role_a.id,
        })
        today = fields.Date.today()
        cls.task_a = cls.env["ops.task"].create({
            "task_def_id": cls.definition_a.id,
            "period_key": "scope-a",
            "scheduled_date": today,
            "due_date": today,
        })
        cls.task_b = cls.env["ops.task"].create({
            "task_def_id": cls.definition_b.id,
            "period_key": "scope-b",
            "scheduled_date": today,
            "due_date": today,
        })

    def test_employee_only_sees_department_tasks(self):
        tasks = self.env["ops.task"].with_user(self.user_a).search([
            ("id", "in", (self.task_a.id, self.task_b.id)),
        ])
        self.assertEqual(tasks, self.task_a)

    def test_manager_sees_all_tasks(self):
        tasks = self.env["ops.task"].with_user(self.manager).search([
            ("id", "in", (self.task_a.id, self.task_b.id)),
        ])
        self.assertEqual(set(tasks.ids), {self.task_a.id, self.task_b.id})

    def test_employee_cannot_complete_other_department_task(self):
        with self.assertRaises(UserError):
            self.task_b.with_user(self.user_a).action_mark_done()

    def test_approver_sees_only_completed_report(self):
        tasks = self.env["ops.task"].with_user(self.user_a).search([
            ("id", "in", (self.task_a.id, self.task_b.id)),
        ])
        self.assertEqual(tasks, self.task_a)

        self.task_b.write({"state": "done"})
        tasks = self.env["ops.task"].with_user(self.user_a).search([
            ("id", "in", (self.task_a.id, self.task_b.id)),
        ])
        self.assertEqual(set(tasks.ids), {self.task_a.id, self.task_b.id})

    def test_direct_role_assignment_is_additive(self):
        self.role_b.write({"user_ids": [(4, self.user_a.id)]})
        tasks = self.env["ops.task"].with_user(self.user_a).search([
            ("id", "in", (self.task_a.id, self.task_b.id)),
        ])
        self.assertEqual(set(tasks.ids), {self.task_a.id, self.task_b.id})

    def test_menu_structure(self):
        root = self.env.ref("cams_ops_process.menu_ops_root")
        self.assertEqual(root.name, "회사 운영 센터")
        self.assertTrue(root.active)
        self.assertIn(self.env.ref("base.group_user"), root.groups_id)
        self.assertEqual(
            self.env.ref("cams_ops_process.menu_ops_today").parent_id,
            root,
        )
        self.assertEqual(
            self.env.ref("cams_ops_process.menu_ops_all").name,
            "업무 현황(전체)",
        )
        self.assertEqual(
            self.env.ref("cams_ops_process.menu_ops_reference_code").action,
            self.env.ref("escon_code.action_escon_code"),
        )
