from odoo import api, fields, models, _


class IatfTrainingRecord(models.Model):
    _name = "iatf.training.record"
    _description = "Training Record (IATF 16949 §7.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "training_date desc"

    name = fields.Char(
        string="교육 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="교육 제목", required=True, tracking=True)
    training_type = fields.Selection(
        [
            ("classroom", "집합 교육"),
            ("ojt", "현장 교육 (OJT)"),
            ("external", "외부 교육"),
            ("elearning", "이러닝"),
            ("certification", "자격 인증 / 갱신"),
        ],
        string="유형", required=True, default="classroom", tracking=True,
    )

    training_date = fields.Date(string="교육일", required=True, default=fields.Date.today)
    duration_hours = fields.Float(string="소요시간 (시간)")
    trainer_id = fields.Many2one("res.users", string="강사")
    trainer_external = fields.Char(string="외부 강사명")

    # ── Participants ──
    employee_ids = fields.Many2many("hr.employee", string="참가자")
    participant_count = fields.Integer(compute="_compute_participant_count")
    department_id = fields.Many2one("hr.department", string="부서")

    # ── Content ──
    topics = fields.Html(string="교육 내용")
    iatf_clause = fields.Char(string="관련 IATF 조항", help="e.g. §7.2, §8.5.1")
    process_name = fields.Char(string="관련 공정")

    # ── Evaluation ──
    evaluation_method = fields.Selection(
        [
            ("test", "필기 시험"),
            ("practical", "실기 시연"),
            ("observation", "상사 관찰"),
            ("quiz", "퀴즈"),
            ("none", "평가 없음"),
        ],
        string="평가 방법", default="none",
    )
    pass_criteria = fields.Char(string="합격 기준", help="e.g. ≥ 80% score")
    effectiveness_verified = fields.Boolean(string="유효성 검증됨", tracking=True)
    effectiveness_notes = fields.Text(string="유효성 비고")

    # ── Status ──
    state = fields.Selection(
        [
            ("planned", "계획됨"),
            ("completed", "완료"),
            ("verified", "유효성 검증됨"),
            ("cancelled", "취소"),
        ],
        string="상태", default="planned", tracking=True,
    )

    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("employee_ids")
    def _compute_participant_count(self):
        for rec in self:
            rec.participant_count = len(rec.employee_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.training.record") or _("New")
        return super().create(vals_list)

    def action_complete(self):
        self.write({"state": "completed"})

    def action_verify_effectiveness(self):
        self.write({"state": "verified", "effectiveness_verified": True})

    def action_cancel(self):
        self.write({"state": "cancelled"})
