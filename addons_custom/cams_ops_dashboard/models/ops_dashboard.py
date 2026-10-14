from datetime import timedelta

from odoo import api, fields, models


class CamsOpsDashboard(models.Model):
    _name = "cams.ops.dashboard"
    _description = "회사 운영 센터 대시보드"

    name = fields.Char(default="운영 대시보드")

    @api.model
    def _assigned_domain(self, user, department_id=False):
        if user.has_group("cams_ops_process.group_ops_manager"):
            if department_id:
                return [("role_id.department_ids", "in", [department_id])]
            return []
        department_ids = user.employee_ids.mapped("department_id").ids
        return [
            "|",
            ("role_id.user_ids", "in", user.id),
            ("role_id.department_ids", "in", department_ids),
        ]

    @api.model
    def _approval_domain(self, user, department_id=False):
        if user.has_group("cams_ops_process.group_ops_manager"):
            if department_id:
                return [("task_def_id.approver_role_id.department_ids", "in", [department_id])]
            return []
        department_ids = user.employee_ids.mapped("department_id").ids
        return [
            "|",
            ("task_def_id.approver_role_id.user_ids", "in", user.id),
            ("task_def_id.approver_role_id.department_ids", "in", department_ids),
        ]

    @api.model
    def _serialize_task(self, task):
        return {
            "id": task.id,
            "label": task.display_label,
            "name": task.task_def_id.name,
            "role": task.role_id.name,
            "scheduled_date": fields.Date.to_string(task.scheduled_date),
            "due_date": fields.Date.to_string(task.due_date),
            "state": task.state,
            "state_label": dict(task._fields["state"].selection).get(task.state, task.state),
            "is_overdue": task.is_overdue,
            "done_by": task.done_uid.name or "",
            "can_complete": task._can_complete(self.env.user),
            "can_approve": task._can_approve(self.env.user),
        }

    @api.model
    def get_dashboard_data(self, limit=20, department_id=False):
        user = self.env.user
        manager = user.has_group("cams_ops_process.group_ops_manager")
        if department_id and not manager:
            department_id = False
        limit = max(1, min(int(limit or 20), 100))
        today = fields.Date.context_today(self)
        week_end = today + timedelta(days=7)
        Task = self.env["ops.task"]

        assigned = self._assigned_domain(user, department_id)
        approvals = self._approval_domain(user, department_id)
        pending_domain = assigned + [("state", "=", "todo")]
        today_domain = pending_domain + [("scheduled_date", "<=", today)]
        overdue_domain = pending_domain + [("due_date", "<", today)]
        approval_domain = approvals + [("state", "=", "done")]
        week_domain = assigned + [
            ("state", "=", "todo"),
            ("scheduled_date", ">", today),
            ("scheduled_date", "<=", week_end),
        ]

        today_tasks = Task.search(today_domain, order="due_date, id", limit=limit)
        approval_tasks = Task.search(approval_domain, order="done_date, due_date, id", limit=limit)
        week_tasks = Task.search(week_domain, order="scheduled_date, due_date, id", limit=limit)

        employee = user.employee_ids[:1]
        departments = user.employee_ids.mapped("department_id")
        roles = self.env["ops.role"].search(self.env["ops.role"]._for_user_domain(user))
        department_options = []
        if manager:
            department_options = [
                {"id": department.id, "name": department.complete_name or department.name}
                for department in self.env["hr.department"].search([], order="complete_name, name")
            ]

        return {
            "user": {
                "name": user.name,
                "employee": employee.name or "",
                "department": ", ".join(departments.mapped("complete_name")),
                "roles": roles.mapped("name"),
                "is_manager": manager,
            },
            "selected_department_id": department_id or False,
            "departments": department_options,
            "counts": {
                "today": Task.search_count(today_domain),
                "overdue": Task.search_count(overdue_domain),
                "approval": Task.search_count(approval_domain),
                "week": Task.search_count(week_domain),
            },
            "today_tasks": [self._serialize_task(task) for task in today_tasks],
            "approval_tasks": [self._serialize_task(task) for task in approval_tasks],
            "week_tasks": [self._serialize_task(task) for task in week_tasks],
        }
