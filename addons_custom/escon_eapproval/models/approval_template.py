from odoo import fields, models


class IatfApprovalTemplateLine(models.Model):
    """결재선 템플릿 라인에 부서/직급 기반 결재자 방식 추가.

    - 부서 내 직급자: 상신자 소속 부서(없으면 상위 부서로 거슬러 올라가며)에서
      지정 직급의 직원을 찾아 결재자로 결정. 본인은 제외.
    - 지정 부서의 부서장: 상신자와 무관하게 특정 부서의 부서장으로 결정.

    결정 불가 시 빈 recordset 을 반환하면 기존 엔진이 템플릿 적용을 포기하고
    수동 지정을 요구한다 (iatf_approval._approval_apply_default_template)."""

    _inherit = "iatf.approval.template.line"

    approver_mode = fields.Selection(
        selection_add=[
            ("job_grade", "부서 내 직급자"),
            ("dept_manager", "지정 부서의 부서장"),
        ],
        ondelete={"job_grade": "set default", "dept_manager": "set default"},
    )
    job_grade_id = fields.Many2one(
        "escon.job.grade", string="직급",
        help="'부서 내 직급자' 방식: 상신자 부서에서 이 직급의 직원(사용자 연결 필수)을 찾습니다. "
             "부서에 없으면 상위 부서로 올라가며 찾고, 상신자 본인은 제외합니다.")
    department_id = fields.Many2one(
        "hr.department", string="지정 부서",
        help="'지정 부서의 부서장' 방식: 이 부서의 부서장이 결재자가 됩니다.")

    def _resolve_user(self, requester):
        self.ensure_one()
        Users = self.env["res.users"]
        if self.approver_mode == "job_grade":
            if not self.job_grade_id:
                return Users
            employee = requester.employee_id
            department = employee.department_id if employee else False
            Employee = self.env["hr.employee"]
            seen = self.env["hr.department"]
            while department and department not in seen:
                seen |= department
                candidate = Employee.search(
                    [
                        ("department_id", "=", department.id),
                        ("job_grade_id", "=", self.job_grade_id.id),
                        ("user_id", "!=", False),
                        ("user_id", "!=", requester.id),
                    ],
                    order="id", limit=1,
                )
                if candidate:
                    return candidate.user_id
                department = department.parent_id
            return Users
        if self.approver_mode == "dept_manager":
            manager = self.department_id.manager_id
            if manager and manager.user_id and manager.user_id != requester:
                return manager.user_id
            return Users
        return super()._resolve_user(requester)
