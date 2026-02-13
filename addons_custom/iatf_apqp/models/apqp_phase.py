from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfApqpPhase(models.Model):
    _name = "iatf.apqp.phase"
    _description = "APQP Phase"
    _order = "phase_number"

    project_id = fields.Many2one(
        "iatf.apqp.project", string="APQP 프로젝트", required=True,
        ondelete="cascade", index=True,
    )
    phase_number = fields.Selection(
        [
            ("1", "Phase 1: Plan & Define"),
            ("2", "Phase 2: Product Design & Dev"),
            ("3", "Phase 3: Process Design & Dev"),
            ("4", "Phase 4: Product & Process Validation"),
            ("5", "Phase 5: Production"),
        ],
        string="Phase", required=True,
    )
    name = fields.Char(string="단계명", required=True)
    description = fields.Html(string="설명")

    # ── Timeline ──
    date_planned_start = fields.Date(string="계획 시작일")
    date_planned_end = fields.Date(string="계획 종료일")
    date_actual_start = fields.Date(string="실제 시작일")
    date_actual_end = fields.Date(string="실제 종료일")

    # ── Gate review ──
    gate_reviewer_id = fields.Many2one("res.users", string="게이트 검토자")
    gate_review_date = fields.Date(string="게이트 검토일")
    gate_result = fields.Selection(
        [
            ("go", "통과"),
            ("conditional", "조건부 통과"),
            ("no_go", "불통과"),
        ],
        string="게이트 결과",
    )
    gate_notes = fields.Text(string="게이트 검토 비고")

    # ── Deliverables ──
    deliverable_ids = fields.One2many("iatf.apqp.deliverable", "phase_id", string="산출물")
    deliverable_count = fields.Integer(compute="_compute_deliverable_stats")
    deliverable_done_count = fields.Integer(compute="_compute_deliverable_stats")
    progress = fields.Float(string="진행률 (%)", compute="_compute_deliverable_stats", store=True)

    state = fields.Selection(
        [
            ("not_started", "Not Started"),
            ("in_progress", "In Progress"),
            ("completed", "Completed"),
        ],
        string="Status", default="not_started",
    )

    @api.depends("deliverable_ids.state")
    def _compute_deliverable_stats(self):
        for phase in self:
            total = len(phase.deliverable_ids)
            done = len(phase.deliverable_ids.filtered(lambda d: d.state == "done"))
            phase.deliverable_count = total
            phase.deliverable_done_count = done
            phase.progress = (done / total * 100.0) if total else 0.0

    def action_start(self):
        self.write({"state": "in_progress", "date_actual_start": fields.Date.today()})

    def action_complete(self):
        for phase in self:
            required_not_done = phase.deliverable_ids.filtered(
                lambda d: d.is_required and d.state != "done"
            )
            if required_not_done:
                raise UserError(
                    _("%d required deliverable(s) not completed.") % len(required_not_done)
                )
        self.write({"state": "completed", "date_actual_end": fields.Date.today()})

    def action_reset(self):
        self.write({"state": "not_started", "date_actual_start": False, "date_actual_end": False})


class IatfApqpPhaseTemplate(models.Model):
    _name = "iatf.apqp.phase.template"
    _description = "APQP Phase Template"
    _order = "phase_number"

    phase_number = fields.Selection(
        [
            ("1", "Phase 1: Plan & Define"),
            ("2", "Phase 2: Product Design & Dev"),
            ("3", "Phase 3: Process Design & Dev"),
            ("4", "Phase 4: Product & Process Validation"),
            ("5", "Phase 5: Production"),
        ],
        string="Phase", required=True,
    )
    name = fields.Char(string="단계명", required=True)
    description = fields.Html(string="설명")
    deliverable_template_ids = fields.One2many(
        "iatf.apqp.deliverable.template", "phase_template_id", string="산출물 템플릿",
    )


class IatfApqpDeliverableTemplate(models.Model):
    _name = "iatf.apqp.deliverable.template"
    _description = "APQP Deliverable Template"
    _order = "sequence"

    phase_template_id = fields.Many2one(
        "iatf.apqp.phase.template", string="단계 템플릿",
        required=True, ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string="산출물명", required=True)
    description = fields.Text(string="설명")
    is_required = fields.Boolean(string="필수", default=True)
