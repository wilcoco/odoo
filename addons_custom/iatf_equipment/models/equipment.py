from odoo import api, fields, models, _


class IatfEquipment(models.Model):
    _name = "iatf.equipment"
    _description = "설비 대장 (IATF 16949 §8.5.1.5)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(string="설비명", required=True, tracking=True)
    code = fields.Char(
        string="설비 코드", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    equipment_type = fields.Selection(
        [
            ("production", "생산 설비"),
            ("assembly", "조립 설비"),
            ("test", "시험/검사 설비"),
            ("utility", "유틸리티"),
            ("transport", "운반 설비"),
            ("other", "기타"),
        ],
        string="설비 유형", required=True, default="production", tracking=True,
    )

    # ── 사양 ──
    manufacturer = fields.Char(string="제조사")
    model_name = fields.Char(string="모델명")
    serial_number = fields.Char(string="시리얼 번호")
    manufacture_year = fields.Char(string="제조 연도")
    purchase_date = fields.Date(string="구입일")
    install_date = fields.Date(string="설치일")
    capacity = fields.Char(string="능력/용량", help="예: 200톤, 1500rpm")
    specification = fields.Html(string="주요 사양")

    # ── 위치/담당 ──
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장")
    location = fields.Char(string="설치 위치")
    department_id = fields.Many2one("hr.department", string="관리 부서")
    responsible_id = fields.Many2one("res.users", string="담당자", tracking=True)

    # ── TPM / 보전 ──
    pm_cycle_days = fields.Integer(string="PM 주기 (일)", default=90)
    last_pm_date = fields.Date(string="최근 PM 일자")
    next_pm_date = fields.Date(string="다음 PM 예정일", compute="_compute_next_pm", store=True)
    is_pm_overdue = fields.Boolean(string="PM 기한 초과", compute="_compute_next_pm", store=True)

    # ── 가동 이력 ──
    total_runtime_hours = fields.Float(string="누적 가동 시간")
    breakdown_count = fields.Integer(string="고장 건수", compute="_compute_breakdown_stats", store=True)
    mtbf = fields.Float(string="MTBF (시간)", compute="_compute_breakdown_stats", store=True,
                         help="평균 고장 간격")
    mttr = fields.Float(string="MTTR (시간)", compute="_compute_breakdown_stats", store=True,
                         help="평균 수리 시간")
    availability_rate = fields.Float(string="가동률 (%)", compute="_compute_breakdown_stats", store=True)

    # ── 관련 기록 ──
    pm_schedule_ids = fields.One2many("iatf.pm.schedule", "equipment_id", string="PM 계획/실적")
    breakdown_ids = fields.One2many("iatf.equipment.breakdown", "equipment_id", string="고장 이력")
    daily_check_ids = fields.One2many("iatf.daily.check", "equipment_id", string="일상점검")
    spare_part_ids = fields.One2many("iatf.equipment.spare", "equipment_id", string="예비부품")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")
    image = fields.Binary(string="설비 사진")

    state = fields.Selection(
        [
            ("draft", "등록"),
            ("active", "가동 중"),
            ("maintenance", "보전 중"),
            ("breakdown", "고장"),
            ("inactive", "비가동"),
            ("disposed", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("last_pm_date", "pm_cycle_days")
    def _compute_next_pm(self):
        today = fields.Date.today()
        for rec in self:
            if rec.last_pm_date and rec.pm_cycle_days:
                from datetime import timedelta
                rec.next_pm_date = rec.last_pm_date + timedelta(days=rec.pm_cycle_days)
                rec.is_pm_overdue = rec.next_pm_date < today
            else:
                rec.next_pm_date = False
                rec.is_pm_overdue = False

    @api.depends("breakdown_ids.downtime_hours", "total_runtime_hours")
    def _compute_breakdown_stats(self):
        for rec in self:
            breakdowns = rec.breakdown_ids.filtered(lambda b: b.state == "closed")
            rec.breakdown_count = len(breakdowns)
            total_downtime = sum(breakdowns.mapped("downtime_hours"))
            if rec.breakdown_count:
                rec.mttr = total_downtime / rec.breakdown_count
                if rec.total_runtime_hours:
                    rec.mtbf = rec.total_runtime_hours / rec.breakdown_count
                else:
                    rec.mtbf = 0.0
            else:
                rec.mttr = 0.0
                rec.mtbf = 0.0
            if rec.total_runtime_hours and (rec.total_runtime_hours + total_downtime) > 0:
                rec.availability_rate = (rec.total_runtime_hours / (rec.total_runtime_hours + total_downtime)) * 100.0
            else:
                rec.availability_rate = 100.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code", _("New")) == _("New"):
                vals["code"] = self.env["ir.sequence"].next_by_code("iatf.equipment") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_maintenance(self):
        self.write({"state": "maintenance"})

    def action_breakdown(self):
        self.write({"state": "breakdown"})

    def action_inactive(self):
        self.write({"state": "inactive"})

    def action_dispose(self):
        self.write({"state": "disposed"})

    @api.model
    def _cron_pm_overdue_alert(self):
        """매일 실행: PM 기한 초과/임박 설비에 activity 알림 생성"""
        from datetime import timedelta
        today = fields.Date.today()
        soon = today + timedelta(days=7)

        # PM 기한 초과
        overdue = self.search([
            ("is_pm_overdue", "=", True),
            ("state", "=", "active"),
        ])
        for eq in overdue:
            eq.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("PM 기한 초과: %s (예정일: %s)") % (eq.name, eq.next_pm_date),
                user_id=eq.responsible_id.id or self.env.ref("base.user_admin").id,
                date_deadline=today,
            )

        # PM 기한 7일 이내
        upcoming = self.search([
            ("next_pm_date", "<=", soon),
            ("next_pm_date", ">=", today),
            ("state", "=", "active"),
        ])
        for eq in upcoming:
            existing = self.env["mail.activity"].search([
                ("res_model", "=", "iatf.equipment"),
                ("res_id", "=", eq.id),
                ("summary", "like", "PM 기한 임박"),
            ], limit=1)
            if not existing:
                eq.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("PM 기한 임박: %s (예정일: %s)") % (eq.name, eq.next_pm_date),
                    user_id=eq.responsible_id.id or self.env.ref("base.user_admin").id,
                    date_deadline=eq.next_pm_date,
                )


class IatfEquipmentSpare(models.Model):
    _name = "iatf.equipment.spare"
    _description = "설비 예비부품"
    _order = "equipment_id, name"

    equipment_id = fields.Many2one("iatf.equipment", string="설비", required=True, ondelete="cascade")
    name = fields.Char(string="부품명", required=True)
    part_number = fields.Char(string="부품 번호")
    quantity_required = fields.Float(string="필요 수량", default=1)
    quantity_on_hand = fields.Float(string="보유 수량")
    supplier = fields.Char(string="공급처")
    lead_time_days = fields.Integer(string="리드타임 (일)")
    notes = fields.Char(string="비고")
