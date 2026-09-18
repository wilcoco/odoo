from odoo import fields, models


class EsconJobGrade(models.Model):
    """직급 (사원/대리/과장/차장/부장/이사 …).

    Odoo 표준 hr.job(직무/직책)과 별개로, 결재선에서 "부서 내 직급자"를
    찾을 때 쓰는 회사 서열 축이다."""

    _name = "escon.job.grade"
    _description = "직급"
    _order = "sequence, id"

    name = fields.Char(string="직급명", required=True)
    sequence = fields.Integer(
        string="서열", default=10,
        help="숫자가 낮을수록 상위 직급 (예: 대표이사 1, 이사 5, 부장 10 … 사원 90)")
    active = fields.Boolean(default=True)
    note = fields.Char(string="비고")

    _sql_constraints = [
        ("name_uniq", "unique(name)", "이미 같은 이름의 직급이 있습니다."),
    ]


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    job_grade_id = fields.Many2one(
        "escon.job.grade", string="직급", tracking=True,
        help="전자결재 결재선의 '부서 내 직급자' 방식이 이 값으로 결재자를 찾습니다.")
