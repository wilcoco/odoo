from odoo import api, fields, models, _


class IatfCompetenceMatrix(models.Model):
    _name = "iatf.competence.matrix"
    _description = "Competence Matrix Entry"
    _order = "employee_id, skill_name"
    _rec_name = "display_name"

    employee_id = fields.Many2one("hr.employee", string="직원", required=True, index=True)
    department_id = fields.Many2one(
        "hr.department", string="부서",
        related="employee_id.department_id", store=True, readonly=True,
    )
    job_id = fields.Many2one(
        "hr.job", string="직책",
        related="employee_id.job_id", store=True, readonly=True,
    )

    skill_name = fields.Char(string="기술 / 역량", required=True)
    skill_category = fields.Selection(
        [
            ("process", "공정 지식"),
            ("quality", "품질 도구"),
            ("safety", "안전"),
            ("regulatory", "규제 / 준법"),
            ("technical", "기술 스킬"),
            ("soft", "소프트 스킬"),
        ],
        string="카테고리", default="process",
    )

    required_level = fields.Selection(
        [
            ("0", "불필요"),
            ("1", "인지"),
            ("2", "감독하에 수행 가능"),
            ("3", "독립 수행 가능"),
            ("4", "타인 교육 가능"),
        ],
        string="요구 수준", default="3",
    )
    current_level = fields.Selection(
        [
            ("0", "미교육"),
            ("1", "인지"),
            ("2", "감독하에 수행 가능"),
            ("3", "독립 수행 가능"),
            ("4", "타인 교육 가능"),
        ],
        string="현재 수준", default="0",
    )
    gap = fields.Boolean(string="차이 존재", compute="_compute_gap", store=True)

    last_training_date = fields.Date(string="최근 교육일")
    next_retraining_date = fields.Date(string="다음 재교육일")
    certification = fields.Char(string="자격증 / 면허")
    expiry_date = fields.Date(string="자격증 만료일")

    notes = fields.Text(string="비고")

    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("required_level", "current_level")
    def _compute_gap(self):
        for rec in self:
            rec.gap = (int(rec.current_level or "0") < int(rec.required_level or "0"))

    @api.depends("employee_id", "skill_name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s — %s" % (rec.employee_id.name or "", rec.skill_name or "")
