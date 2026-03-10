from odoo import fields, models


class GenerateMOWizard(models.TransientModel):
    _name = "injection.generate.mo.wizard"
    _description = "MO 생성 확인 위자드"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행", required=True,
    )
    line_count = fields.Integer(
        string="계획 라인 수", compute="_compute_summary",
    )
    total_qty = fields.Float(
        string="총 계획 수량", compute="_compute_summary",
    )
    changeover_count = fields.Integer(
        string="금형 교체 횟수", compute="_compute_summary",
    )

    def _compute_summary(self):
        for rec in self:
            lines = rec.planning_run_id.line_ids.filtered(
                lambda l: l.state == "draft"
            )
            rec.line_count = len(lines)
            rec.total_qty = sum(lines.mapped("planned_qty"))
            rec.changeover_count = len(lines.filtered("changeover_needed"))

    def action_generate(self):
        """MO 생성 실행"""
        self.ensure_one()
        self.planning_run_id.generate_manufacturing_orders()
        return {"type": "ir.actions.act_window_close"}
