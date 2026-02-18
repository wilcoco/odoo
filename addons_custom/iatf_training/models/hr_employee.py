from odoo import api, fields, models, _


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    # ── IATF 교육/역량 연동 (B2) ──
    training_record_ids = fields.Many2many(
        "iatf.training.record", compute="_compute_training_records",
        string="교육 이력",
    )
    training_count = fields.Integer(compute="_compute_training_records", string="교육 건수")
    competence_matrix_ids = fields.One2many(
        "iatf.competence.matrix", "employee_id", string="역량 매트릭스",
    )
    competence_count = fields.Integer(compute="_compute_competence_count", string="역량 항목")
    avg_competence_level = fields.Float(
        compute="_compute_competence_count", string="평균 역량 수준",
    )

    def _compute_training_records(self):
        TR = self.env.get("iatf.training.record")
        for emp in self:
            if TR:
                recs = TR.search([("employee_ids", "in", emp.id)])
                emp.training_record_ids = recs
                emp.training_count = len(recs)
            else:
                emp.training_record_ids = False
                emp.training_count = 0

    def _compute_competence_count(self):
        for emp in self:
            matrices = emp.competence_matrix_ids
            emp.competence_count = len(matrices)
            if matrices:
                level_map = {"none": 0, "awareness": 1, "basic": 2, "competent": 3, "expert": 4}
                levels = [level_map.get(m.current_level, 0) for m in matrices]
                emp.avg_competence_level = sum(levels) / len(levels)
            else:
                emp.avg_competence_level = 0.0

    def action_view_training_records(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.training.record",
            "view_mode": "list,form",
            "domain": [("employee_ids", "in", self.id)],
            "name": _("교육 이력: %s") % self.name,
        }

    def action_view_competence_matrix(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.competence.matrix",
            "view_mode": "list,form",
            "domain": [("employee_id", "=", self.id)],
            "name": _("역량 매트릭스: %s") % self.name,
            "context": {"default_employee_id": self.id},
        }
