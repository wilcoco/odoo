from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfNonconformity(models.Model):
    _name = "iatf.nonconformity"
    _description = "Nonconformity Report (IATF 16949 §10.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    # ── Identification ──
    name = fields.Char(
        string="부적합 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)

    nc_type = fields.Selection(
        [
            ("internal", "내부 부적합"),
            ("supplier", "협력업체 부적합"),
            ("customer", "고객 불만"),
            ("audit", "심사 지적사항"),
            ("process", "공정 부적합"),
        ],
        string="부적합 유형", required=True, default="internal", tracking=True,
    )
    severity = fields.Selection(
        [
            ("minor", "경미"),
            ("major", "중대"),
            ("critical", "치명적"),
        ],
        string="심각도", required=True, default="minor", tracking=True,
    )
    priority = fields.Selection(
        [
            ("0", "보통"),
            ("1", "높음"),
            ("2", "긴급"),
        ],
        string="우선순위", default="0",
    )

    # ── 8D Discipline mapping ──
    # D1: Team
    team_leader_id = fields.Many2one("res.users", string="팀 리더 (D1)", tracking=True)
    team_member_ids = fields.Many2many("res.users", string="팀원 (D1)")

    # D2: Problem Description
    problem_description = fields.Html(string="문제 기술 (D2)", tracking=True)
    detection_date = fields.Date(string="발견 일자", default=fields.Date.today, required=True)
    detection_location = fields.Char(string="발견 장소")
    detected_by = fields.Many2one("res.users", string="발견자", default=lambda self: self.env.user)

    # D3: Interim Containment Action
    containment_action = fields.Html(string="격리 조치 (D3)")
    containment_date = fields.Date(string="격리 일자")
    containment_responsible_id = fields.Many2one("res.users", string="격리 담당자")
    containment_verified = fields.Boolean(string="격리 검증")

    # D4: Root Cause Analysis
    root_cause_method = fields.Selection(
        [
            ("5why", "5-Why 분석"),
            ("fishbone", "특성요인도"),
            ("fta", "결함수 분석"),
            ("other", "기타"),
        ],
        string="원인분석 방법 (D4)",
    )
    root_cause = fields.Html(string="근본 원인 (D4)")

    # D5 & D6: handled via corrective_action_ids
    # D7: Preventive Action
    preventive_action = fields.Html(string="예방/시스템 조치 (D7)")

    # D6: Verification
    verification_result = fields.Html(string="유효성 검증 (D6)")

    # D7: Preventive — already defined below

    # D8: Closure
    closure_notes = fields.Html(string="팀 인정/종료 기록 (D8)")

    # ── Timeline ──
    target_close_date = fields.Date(string="목표 종료일", tracking=True)
    actual_close_date = fields.Date(string="실제 종료일")

    # ── Responsible ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)

    notes = fields.Text(string="비고")

    # ── References ──
    product_id = fields.Many2one("product.product", string="제품")
    production_id = fields.Many2one("mrp.production", string="제조 오더")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")
    partner_id = fields.Many2one(
        "res.partner", string="관련 파트너",
        help="Customer (complaint) or Supplier (supplier NC)",
    )
    quantity_affected = fields.Float(string="영향 수량")
    quantity_rejected = fields.Float(string="불합격 수량")

    # ── Disposition ──
    disposition = fields.Selection(
        [
            ("use_as_is", "현상태 사용"),
            ("rework", "재작업"),
            ("scrap", "폐기"),
            ("return", "협력업체 반품"),
            ("sort", "전수 선별"),
            ("concession", "고객 특채"),
        ],
        string="처리 방법", tracking=True,
    )

    # ── Relations ──
    corrective_action_ids = fields.One2many(
        "iatf.corrective.action", "nonconformity_id", string="시정 조치 (D5/D6)",
    )
    corrective_action_count = fields.Integer(compute="_compute_ca_count")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="증빙 / 첨부파일")

    # ── Workflow ──
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("containment", "D3 격리"),
            ("analysis", "D4 원인분석"),
            ("corrective", "D5/D6 시정조치"),
            ("verification", "D7 검증"),
            ("closed", "D8 종료"),
            ("cancelled", "취소"),
        ],
        string="상태", default="draft", required=True, tracking=True,
    )

    company_id = fields.Many2one(
        "res.company", string="회사", default=lambda self: self.env.company,
    )

    # ── Cost tracking ──
    cost_internal = fields.Float(string="내부 비용")
    cost_external = fields.Float(string="외부 비용")
    cost_total = fields.Float(string="총 비용", compute="_compute_cost_total", store=True)
    account_move_id = fields.Many2one("account.move", string="COPQ 전표", readonly=True, copy=False)

    @api.depends("cost_internal", "cost_external")
    def _compute_cost_total(self):
        for rec in self:
            rec.cost_total = rec.cost_internal + rec.cost_external

    def action_post_copq_journal(self):
        """COPQ 비용을 회계 전표로 전기 (B4)"""
        self.ensure_one()
        if self.account_move_id:
            raise UserError(_("이미 전표가 생성되어 있습니다: %s") % self.account_move_id.name)
        if not self.cost_total:
            raise UserError(_("비용이 0이므로 전표를 생성할 수 없습니다."))

        journal = self.env["account.journal"].search([("type", "=", "general")], limit=1)
        if not journal:
            raise UserError(_("일반 분개장을 찾을 수 없습니다."))

        # COPQ 비용 계정 / 미지급금 계정 (기본 계정으로 대체 가능)
        expense_account = self.env["account.account"].search([
            ("account_type", "=", "expense"),
            ("company_id", "=", self.company_id.id),
        ], limit=1)
        payable_account = self.env["account.account"].search([
            ("account_type", "=", "liability_current"),
            ("company_id", "=", self.company_id.id),
        ], limit=1)

        if not expense_account or not payable_account:
            raise UserError(_("COPQ 비용 계정 또는 미지급 계정을 찾을 수 없습니다. 회계 설정을 확인하세요."))

        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": journal.id,
            "date": fields.Date.today(),
            "ref": _("COPQ: %s") % self.name,
            "line_ids": [
                (0, 0, {
                    "name": _("불량비용(COPQ) — %s") % self.title,
                    "account_id": expense_account.id,
                    "debit": self.cost_total,
                    "credit": 0,
                }),
                (0, 0, {
                    "name": _("불량비용(COPQ) — %s") % self.title,
                    "account_id": payable_account.id,
                    "debit": 0,
                    "credit": self.cost_total,
                }),
            ],
        })
        self.account_move_id = move.id
        self.message_post(body=_("COPQ 회계 전표 %s 생성됨 (금액: %s)") % (
            move.name, "{:,.0f}".format(self.cost_total)))

    @api.depends("corrective_action_ids")
    def _compute_ca_count(self):
        for rec in self:
            rec.corrective_action_count = len(rec.corrective_action_ids)

    # ── CRUD ──

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.nonconformity") or _("New")
        records = super().create(vals_list)
        for rec in records:
            rec._auto_check_scar_threshold()
            rec._auto_update_risk()
        return records

    def _auto_check_scar_threshold(self):
        """업체 NC 3건 이상 반복 시 SCAR 자동 생성 (L2-12)"""
        if self.nc_type != "supplier" or not self.partner_id:
            return
        SCAR = self.env.get("iatf.scar")
        if SCAR is None:
            return
        from datetime import timedelta
        six_months_ago = fields.Date.today() - timedelta(days=180)
        recent_nc_count = self.search_count([
            ("nc_type", "=", "supplier"),
            ("partner_id", "=", self.partner_id.id),
            ("detection_date", ">=", six_months_ago),
        ])
        if recent_nc_count >= 3:
            existing_scar = SCAR.search([
                ("supplier_id", "=", self.partner_id.id),
                ("state", "not in", ("closed", "cancelled")),
            ], limit=1)
            if not existing_scar:
                scar = SCAR.create({
                    "supplier_id": self.partner_id.id,
                    "product_id": self.product_id.id if self.product_id else False,
                    "problem_description": "<p>6개월간 부적합 %d건 반복 발생으로 SCAR 자동 발행<br/>최근 NC: %s</p>" % (
                        recent_nc_count, self.name),
                    "nonconformity_id": self.id,
                    "response_due_date": fields.Date.today() + timedelta(days=14),
                })
                self.message_post(body=_("SCAR %s 자동 발행됨 (6개월 NC %d건)") % (scar.name, recent_nc_count))

    def _auto_update_risk(self):
        """NC 발생 시 관련 리스크 등급 재평가 알림 (L2-17)"""
        RiskReg = self.env.get("iatf.risk.register")
        if RiskReg is None:
            return
        risks = RiskReg.search([
            ("state", "not in", ("closed",)),
        ])
        for risk in risks:
            if self.product_id and hasattr(risk, "description") and risk.description:
                if self.product_id.name in (risk.description or ""):
                    risk.activity_schedule(
                        "mail.mail_activity_data_warning",
                        summary=_("관련 NC 발생으로 리스크 재평가 필요: %s") % self.name,
                        user_id=risk.responsible_id.id if risk.responsible_id else self.env.user.id,
                    )

    # ── Workflow actions ──

    def action_start_containment(self):
        self.write({"state": "containment"})

    def action_start_analysis(self):
        for rec in self:
            if not rec.containment_action:
                raise UserError(_("Please document the containment action (D3) before proceeding."))
        self.write({"state": "analysis"})

    def action_start_corrective(self):
        for rec in self:
            if not rec.root_cause:
                raise UserError(_("Please document the root cause (D4) before proceeding."))
        self.write({"state": "corrective"})

    def action_start_verification(self):
        for rec in self:
            if not rec.corrective_action_ids:
                raise UserError(_("Please add at least one corrective action (D5/D6)."))
        self.write({"state": "verification"})

    def action_close(self):
        for rec in self:
            open_cas = rec.corrective_action_ids.filtered(lambda ca: ca.state != "verified")
            if open_cas:
                raise UserError(
                    _("All corrective actions must be verified before closing. "
                      "%d action(s) still open.") % len(open_cas)
                )
        self.write({"state": "closed"})

    @api.model
    def _cron_nc_closure_check(self):
        """NC 폐쇄루프 검증 cron — 장기 미종결 NC 알림 (L5-3)"""
        from datetime import timedelta
        today = fields.Date.today()
        threshold_30 = today - timedelta(days=30)
        threshold_60 = today - timedelta(days=60)

        # 30일 초과 미종결 NC → 담당자 경고
        stale_ncs = self.search([
            ("state", "not in", ("closed", "cancelled")),
            ("detection_date", "<=", threshold_30),
        ])
        for nc in stale_ncs:
            days_open = (today - nc.detection_date).days if nc.detection_date else 0
            user_id = nc.responsible_id.id if nc.responsible_id else self.env.ref("base.user_admin").id
            if days_open >= 60:
                nc.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("NC %s 가 %d일째 미종결 — 즉시 조치 필요") % (nc.name, days_open),
                    user_id=user_id,
                )
            elif days_open >= 30:
                nc.activity_schedule(
                    "mail.mail_activity_data_warning",
                    summary=_("NC %s 가 %d일째 미종결 — CAPA 진행 확인 필요") % (nc.name, days_open),
                    user_id=user_id,
                )

        # CAPA 유효성 미검증 체크: verification 상태에서 14일 초과
        verify_threshold = today - timedelta(days=14)
        verify_ncs = self.search([
            ("state", "=", "verification"),
            ("write_date", "<=", verify_threshold),
        ])
        for nc in verify_ncs:
            nc.message_post(body=_(
                "CAPA 유효성 검증이 14일 초과하여 지연되고 있습니다. 검증 완료 후 NC를 종결하세요."))

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def action_view_corrective_actions(self):
        self.ensure_one()
        return {
            "name": _("Corrective Actions"),
            "type": "ir.actions.act_window",
            "res_model": "iatf.corrective.action",
            "view_mode": "list,form",
            "domain": [("nonconformity_id", "=", self.id)],
            "context": {"default_nonconformity_id": self.id},
        }
