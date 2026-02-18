from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfApqpProject(models.Model):
    _name = "iatf.apqp.project"
    _description = "APQP Project (IATF 16949 §8.3)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="프로젝트 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="프로젝트 제목", required=True, tracking=True)
    description = fields.Html(string="설명")

    # ── Product / Customer ──
    product_id = fields.Many2one("product.product", string="제품")
    customer_id = fields.Many2one("res.partner", string="고객", tracking=True)
    part_number = fields.Char(string="부품 번호")

    # ── Team ──
    project_leader_id = fields.Many2one("res.users", string="프로젝트 리더",
                                         default=lambda self: self.env.user, tracking=True)
    team_member_ids = fields.Many2many("res.users", string="팀원")

    # ── Timeline ──
    date_start = fields.Date(string="시작일", tracking=True)
    date_target_sop = fields.Date(string="목표 SOP 일자",
                                   help="Start of Production target date", tracking=True)
    date_actual_sop = fields.Date(string="실제 SOP 일자")

    # ── Phases ──
    phase_ids = fields.One2many("iatf.apqp.phase", "project_id", string="APQP 단계")
    current_phase = fields.Selection(
        [
            ("1", "Phase 1: Plan & Define"),
            ("2", "Phase 2: Product Design & Dev"),
            ("3", "Phase 3: Process Design & Dev"),
            ("4", "Phase 4: Product & Process Validation"),
            ("5", "Phase 5: Production"),
        ],
        string="현재 단계", compute="_compute_current_phase", store=True,
    )
    progress = fields.Float(string="전체 진행률 (%)", compute="_compute_progress", store=True)

    # ── Status ──
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("active", "진행 중"),
            ("on_hold", "보류"),
            ("completed", "완료"),
            ("cancelled", "취소"),
        ],
        string="상태", default="draft", tracking=True,
    )

    # ── Links ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    odoo_project_id = fields.Many2one("project.project", string="연결된 Odoo 프로젝트")

    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("phase_ids.state")
    def _compute_current_phase(self):
        for proj in self:
            active_phases = proj.phase_ids.filtered(lambda p: p.state == "in_progress")
            if active_phases:
                proj.current_phase = active_phases[0].phase_number
            else:
                not_started = proj.phase_ids.filtered(lambda p: p.state == "not_started")
                proj.current_phase = not_started[0].phase_number if not_started else "5"

    @api.depends("phase_ids.progress")
    def _compute_progress(self):
        for proj in self:
            phases = proj.phase_ids
            if phases:
                proj.progress = sum(phases.mapped("progress")) / len(phases)
            else:
                proj.progress = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.apqp.project") or _("New")
        return super().create(vals_list)

    def action_auto_advance(self):
        """APQP 5단계 End-to-End 자동 진행 (L4-1)
        현재 단계 완료 확인 → 다음 단계 자동 시작 + 관련 산출물 자동 생성"""
        self.ensure_one()
        for phase in self.phase_ids.sorted("phase_number"):
            if phase.state == "completed":
                continue
            if phase.state == "not_started":
                phase.action_start()
                self.message_post(body=_("APQP Phase %s 자동 시작됨") % phase.phase_number)
            # Phase 2 완료 시 → FMEA 자동 생성
            if phase.phase_number == "2" and phase.state == "completed":
                self._auto_create_fmea()
            # Phase 3 완료 시 → Control Plan 자동 생성
            if phase.phase_number == "3" and phase.state == "completed":
                self._auto_create_control_plan()
            # Phase 4 완료 시 → PPAP 자동 생성
            if phase.phase_number == "4" and phase.state == "completed":
                self._auto_create_ppap()
            break

    def _auto_create_fmea(self):
        FMEA = self.env.get("iatf.fmea")
        if FMEA is None or not self.product_id:
            return
        existing = FMEA.search([("product_id", "=", self.product_id.id)], limit=1)
        if not existing:
            FMEA.create({
                "title": _("PFMEA: %s") % self.product_id.name,
                "fmea_type": "pfmea",
                "product_id": self.product_id.id,
                "customer_id": self.customer_id.id if self.customer_id else False,
            })
            self.message_post(body=_("APQP Phase 2 완료 → PFMEA 자동 생성됨"))

    def _auto_create_control_plan(self):
        CP = self.env.get("iatf.control.plan")
        if CP is None or not self.product_id:
            return
        existing = CP.search([("product_id", "=", self.product_id.id)], limit=1)
        if not existing:
            CP.create({
                "plan_type": "pre_launch",
                "product_id": self.product_id.id,
                "customer_id": self.customer_id.id if self.customer_id else False,
            })
            self.message_post(body=_("APQP Phase 3 완료 → Control Plan (Pre-Launch) 자동 생성됨"))

    def _auto_create_ppap(self):
        PPAP = self.env.get("iatf.ppap.submission")
        if PPAP is None or not self.product_id:
            return
        existing = PPAP.search([("product_id", "=", self.product_id.id)], limit=1)
        if not existing:
            PPAP.create({
                "title": _("PPAP: %s") % self.product_id.name,
                "product_id": self.product_id.id,
                "customer_id": self.customer_id.id if self.customer_id else False,
                "apqp_project_id": self.id,
                "submission_level": "3",
            })
            self.message_post(body=_("APQP Phase 4 완료 → PPAP 제출 자동 생성됨"))

    def action_activate(self):
        self.write({"state": "active"})

    def action_hold(self):
        self.write({"state": "on_hold"})

    def action_complete(self):
        for proj in self:
            incomplete = proj.phase_ids.filtered(lambda p: p.state != "completed")
            if incomplete:
                raise UserError(
                    _("All phases must be completed. %d phase(s) remain.") % len(incomplete)
                )
        self.write({"state": "completed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_create_phases_from_template(self):
        self.ensure_one()
        if self.phase_ids:
            raise UserError(_("Phases already exist. Delete them first to re-create from template."))
        template_phases = self.env["iatf.apqp.phase.template"].search([], order="phase_number")
        for tmpl in template_phases:
            phase = self.env["iatf.apqp.phase"].create({
                "project_id": self.id,
                "phase_number": tmpl.phase_number,
                "name": tmpl.name,
                "description": tmpl.description,
            })
            for del_tmpl in tmpl.deliverable_template_ids:
                self.env["iatf.apqp.deliverable"].create({
                    "phase_id": phase.id,
                    "name": del_tmpl.name,
                    "description": del_tmpl.description,
                    "is_required": del_tmpl.is_required,
                })
        return True
