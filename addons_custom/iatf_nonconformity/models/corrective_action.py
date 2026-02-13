from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfCorrectiveAction(models.Model):
    _name = "iatf.corrective.action"
    _description = "Corrective / Preventive Action (IATF 16949 §10.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="시정조치 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    nonconformity_id = fields.Many2one(
        "iatf.nonconformity", string="부적합", required=True,
        ondelete="cascade", index=True, tracking=True,
    )
    ca_type = fields.Selection(
        [
            ("correction", "수정 (즉시 조치)"),
            ("corrective", "시정 조치 (원인 제거)"),
            ("preventive", "예방 조치 (재발 방지)"),
        ],
        string="조치 유형", required=True, default="corrective", tracking=True,
    )
    description = fields.Html(string="조치 내용", required=True)
    responsible_id = fields.Many2one("res.users", string="담당자", required=True, tracking=True)
    due_date = fields.Date(string="기한", required=True, tracking=True)
    completion_date = fields.Date(string="완료일")

    # ── Verification ──
    verification_method = fields.Text(string="검증 방법")
    verification_result = fields.Html(string="검증 결과")
    verified_by = fields.Many2one("res.users", string="검증자")
    verification_date = fields.Date(string="검증 일자")
    effective = fields.Selection(
        [
            ("yes", "유효"),
            ("no", "무효"),
            ("partial", "부분 유효"),
        ],
        string="유효성", tracking=True,
    )

    # ── Status ──
    state = fields.Selection(
        [
            ("open", "미결"),
            ("in_progress", "진행 중"),
            ("implemented", "실행 완료"),
            ("verified", "검증 완료"),
            ("closed", "종료"),
        ],
        string="상태", default="open", required=True, tracking=True,
    )

    attachment_ids = fields.Many2many("ir.attachment", string="증빙")
    company_id = fields.Many2one(
        "res.company", string="회사", related="nonconformity_id.company_id", store=True,
    )

    is_overdue = fields.Boolean(compute="_compute_is_overdue", store=True)

    @api.depends("due_date", "state")
    def _compute_is_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = (
                rec.due_date and rec.due_date < today and rec.state not in ("verified", "closed")
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.corrective.action") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "in_progress"})

    def action_implement(self):
        self.write({"state": "implemented", "completion_date": fields.Date.today()})

    def action_verify(self):
        for rec in self:
            if not rec.effective:
                raise UserError(_("Please set the Effectiveness evaluation before verifying."))
        self.write({
            "state": "verified",
            "verified_by": self.env.user.id,
            "verification_date": fields.Date.today(),
        })

    def action_close(self):
        for rec in self:
            if rec.state != "verified":
                raise UserError(_("Action must be verified before closing."))
        self.write({"state": "closed"})

    def action_reopen(self):
        self.write({"state": "open", "effective": False, "verified_by": False, "verification_date": False})
