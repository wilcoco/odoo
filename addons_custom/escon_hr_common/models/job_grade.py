from odoo import fields, models


class EsconJobGrade(models.Model):
    """회사 공통 직급(사원/대리/과장/차장/부장/이사 등)."""

    _name = "escon.job.grade"
    _description = "직급"
    _order = "sequence, id"

    name = fields.Char(string="직급명", required=True)
    sequence = fields.Integer(
        string="서열",
        default=10,
        help="숫자가 낮을수록 상위 직급입니다.",
    )
    active = fields.Boolean(default=True)
    note = fields.Char(string="비고")

    _sql_constraints = [
        ("name_uniq", "unique(name)", "이미 같은 이름의 직급이 있습니다."),
    ]


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    job_grade_id = fields.Many2one(
        "escon.job.grade",
        string="직급",
        tracking=True,
        help="회사 운영 역할과 전자결재 결재선에서 공통으로 사용하는 직급입니다.",
    )
