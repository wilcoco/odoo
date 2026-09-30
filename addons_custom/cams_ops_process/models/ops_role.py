from odoo import fields, models


class OpsRole(models.Model):
    """운영 역할(회계·정산·원가·생산관리·사출현장·품질·조립·구매·경영).

    사용자를 역할에 배정하면 '내 업무' 필터와 담당 표시에 사용된다."""

    _name = "ops.role"
    _description = "운영 역할"
    _order = "sequence, id"

    name = fields.Char(string="역할", required=True)
    sequence = fields.Integer(default=10)
    user_ids = fields.Many2many("res.users", string="배정 사용자",
                                help="이 역할을 수행하는 사용자들. '내 업무' 필터 기준.")
    department_ids = fields.Many2many(
        "hr.department",
        string="담당 부서",
        help="이 역할을 수행하는 부서입니다. 부서 소속 임직원에게 해당 역할의 업무가 표시됩니다.",
    )
    task_def_ids = fields.One2many("ops.task.def", "role_id", string="업무 정의")
    task_def_count = fields.Integer(compute="_compute_counts")
    note = fields.Text(string="역할 설명")
    active = fields.Boolean(default=True)

    def _compute_counts(self):
        for r in self:
            r.task_def_count = len(r.task_def_ids)

    @classmethod
    def _for_user_domain(cls, user):
        """직접 지정 또는 임직원 부서에 배정된 역할 범위."""
        department_ids = user.employee_ids.mapped("department_id").ids
        return [
            "|",
            ("user_ids", "in", user.id),
            ("department_ids", "in", department_ids),
        ]
