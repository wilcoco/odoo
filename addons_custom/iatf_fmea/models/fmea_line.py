from odoo import api, fields, models, _


class IatfFmeaLine(models.Model):
    _name = "iatf.fmea.line"
    _description = "FMEA Line Item (Failure Mode)"
    _order = "rpn desc, id"

    fmea_id = fields.Many2one(
        "iatf.fmea", string="FMEA", required=True, ondelete="cascade", index=True,
    )
    fmea_type = fields.Selection(related="fmea_id.fmea_type", store=True, readonly=True)

    # ── Step 1: Structure Analysis ──
    process_step = fields.Char(string="공정 단계 / 기능")
    process_function = fields.Text(string="요구사항 / 기능")

    # ── Step 2: Function Analysis ──
    failure_mode = fields.Char(string="고장 모드", required=True)
    failure_effect = fields.Text(string="고장 영향")
    failure_cause = fields.Text(string="고장 원인")

    # ── Step 3: Failure Analysis (S/O/D ratings) ──
    severity = fields.Integer(
        string="심각도 (S)", default=1,
        help="1 = No effect, 10 = Hazardous without warning",
    )
    occurrence = fields.Integer(
        string="발생도 (O)", default=1,
        help="1 = Remote, 10 = Very high / Almost certain",
    )
    detection = fields.Integer(
        string="검출도 (D)", default=1,
        help="1 = Almost certain detection, 10 = No detection",
    )
    rpn = fields.Integer(
        string="RPN", compute="_compute_rpn", store=True,
        help="Risk Priority Number = S × O × D",
    )

    # ── AIAG-VDA Action Priority (AP) ──
    action_priority = fields.Selection(
        [
            ("high", "높음"),
            ("medium", "보통"),
            ("low", "낮음"),
        ],
        string="조치 우선순위 (AP)", compute="_compute_action_priority", store=True,
    )

    # ── Step 4: Current Controls ──
    current_prevention = fields.Text(string="현재 예방 관리")
    current_detection = fields.Text(string="현재 검출 관리")

    # ── Step 5: Recommended Actions ──
    recommended_action = fields.Text(string="권장 조치")
    action_responsible_id = fields.Many2one("res.users", string="조치 담당자")
    action_due_date = fields.Date(string="조치 기한")
    action_status = fields.Selection(
        [
            ("open", "미결"),
            ("in_progress", "진행 중"),
            ("completed", "완료"),
            ("verified", "검증 완료"),
        ],
        string="조치 상태", default="open",
    )
    action_taken = fields.Text(string="수행 조치")
    action_completion_date = fields.Date(string="완료일")

    # ── Step 6: Re-evaluation after action ──
    severity_after = fields.Integer(string="S (조치 후)", default=0)
    occurrence_after = fields.Integer(string="O (조치 후)", default=0)
    detection_after = fields.Integer(string="D (조치 후)", default=0)
    rpn_after = fields.Integer(
        string="RPN (조치 후)", compute="_compute_rpn_after", store=True,
    )

    # ── Special characteristics ──
    special_characteristic = fields.Selection(
        [
            ("none", "없음"),
            ("cc", "CC - Critical Characteristic"),
            ("sc", "SC - Significant Characteristic"),
            ("hi", "HI - High Impact"),
        ],
        string="특별 특성", default="none",
    )

    notes = fields.Text(string="비고")

    def write(self, vals):
        """RPN 변경 시 관련 Control Plan에 알림"""
        rpn_fields = {"severity", "occurrence", "detection"}
        trigger = rpn_fields & set(vals.keys())
        old_rpns = {}
        if trigger:
            for rec in self:
                old_rpns[rec.id] = rec.rpn

        res = super().write(vals)

        if trigger:
            for rec in self:
                old_rpn = old_rpns.get(rec.id, 0)
                if rec.rpn != old_rpn and rec.fmea_id and rec.fmea_id.product_id:
                    cps = self.env.get("iatf.control.plan")
                    if cps is not None:
                        plans = cps.search([
                            ("product_id", "=", rec.fmea_id.product_id.id),
                            ("state", "=", "approved"),
                        ])
                        for cp in plans:
                            cp.message_post(
                                body=_("⚠ FMEA RPN 변경: %s → %s (고장모드: %s, FMEA: %s)") % (
                                    old_rpn, rec.rpn, rec.failure_mode, rec.fmea_id.name),
                                subject=_("FMEA RPN 변경 알림"),
                            )
                    if rec.rpn >= 200 and old_rpn < 200:
                        rec.fmea_id.activity_schedule(
                            "mail.mail_activity_data_warning",
                            summary=_("고위험 RPN ≥200: %s (RPN=%d)") % (rec.failure_mode, rec.rpn),
                            user_id=rec.action_responsible_id.id or rec.fmea_id.responsible_id.id or self.env.user.id,
                        )
        return res

    @api.depends("severity", "occurrence", "detection")
    def _compute_rpn(self):
        for line in self:
            line.rpn = line.severity * line.occurrence * line.detection

    @api.depends("severity_after", "occurrence_after", "detection_after")
    def _compute_rpn_after(self):
        for line in self:
            line.rpn_after = line.severity_after * line.occurrence_after * line.detection_after

    @api.depends("severity", "occurrence", "detection")
    def _compute_action_priority(self):
        for line in self:
            s, o, d = line.severity, line.occurrence, line.detection
            if s >= 9 or (s >= 7 and o >= 4) or (line.rpn >= 200):
                line.action_priority = "high"
            elif (s >= 5 and o >= 4) or (line.rpn >= 100):
                line.action_priority = "medium"
            else:
                line.action_priority = "low"
