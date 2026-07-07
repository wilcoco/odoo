from odoo import api, fields, models, _


class IatfSupplierEvaluation(models.Model):
    _name = "iatf.supplier.evaluation"
    _description = "Supplier Quality Evaluation (IATF 16949 §8.4)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "evaluation_date desc"

    name = fields.Char(
        string="평가 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    supplier_id = fields.Many2one("res.partner", string="협력업체", required=True,
                                   domain="[('supplier_rank','>',0)]", tracking=True)
    evaluation_date = fields.Date(string="평가일", default=fields.Date.today, required=True)
    evaluation_period = fields.Char(string="평가 기간", help="e.g. 2026-Q1")
    evaluator_id = fields.Many2one("res.users", string="평가자", default=lambda self: self.env.user)

    # ── Scoring criteria ──
    score_quality = fields.Float(string="품질 점수 (0-100)", default=0)
    score_delivery = fields.Float(string="납기 점수 (0-100)", default=0)
    score_cost = fields.Float(string="비용 점수 (0-100)", default=0)
    score_responsiveness = fields.Float(string="대응력 점수 (0-100)", default=0)
    score_system = fields.Float(string="QMS/인증 점수 (0-100)", default=0)

    weight_quality = fields.Float(string="품질 가중치 (%)", default=40)
    weight_delivery = fields.Float(string="납기 가중치 (%)", default=25)
    weight_cost = fields.Float(string="비용 가중치 (%)", default=15)
    weight_responsiveness = fields.Float(string="대응력 가중치 (%)", default=10)
    weight_system = fields.Float(string="품질경영시스템 가중치 (%)", default=10)

    total_score = fields.Float(string="총점", compute="_compute_total_score", store=True)
    grade = fields.Selection(
        [
            ("a", "A — 우수 (≥ 90)"),
            ("b", "B — 승인 (70–89)"),
            ("c", "C — 조건부 (50–69)"),
            ("d", "D — 부적격 (< 50)"),
        ],
        string="등급", compute="_compute_total_score", store=True,
    )

    # ── Details ──
    ppm_rate = fields.Float(string="PPM 비율")
    on_time_delivery_pct = fields.Float(string="납기준수율 (%)")
    certification = fields.Char(string="인증 (ISO/IATF)")
    nc_count_period = fields.Integer(string="기간 내 부적합 수")
    scar_count_period = fields.Integer(string="기간 내 SCAR 수")

    notes = fields.Html(string="비고 / 개선 계획")
    state = fields.Selection(
        [("draft", "초안"), ("confirmed", "확정"), ("closed", "종료")],
        default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("score_quality", "score_delivery", "score_cost", "score_responsiveness", "score_system",
                 "weight_quality", "weight_delivery", "weight_cost", "weight_responsiveness", "weight_system")
    def _compute_total_score(self):
        for rec in self:
            total_weight = (rec.weight_quality + rec.weight_delivery + rec.weight_cost
                            + rec.weight_responsiveness + rec.weight_system) or 100
            total = (
                rec.score_quality * rec.weight_quality
                + rec.score_delivery * rec.weight_delivery
                + rec.score_cost * rec.weight_cost
                + rec.score_responsiveness * rec.weight_responsiveness
                + rec.score_system * rec.weight_system
            ) / total_weight
            rec.total_score = total
            if total >= 90:
                rec.grade = "a"
            elif total >= 70:
                rec.grade = "b"
            elif total >= 50:
                rec.grade = "c"
            else:
                rec.grade = "d"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.supplier.evaluation") or _("New")
        return super().create(vals_list)

    def action_auto_score(self):
        """업체 실적 기반 자동 채점 (L5-2)"""
        self.ensure_one()
        from datetime import timedelta
        today = fields.Date.today()
        period_start = today - timedelta(days=90)
        supplier = self.supplier_id

        # ── 품질 점수: IQC 합격률 기반 ──
        IQC = self.env.get("iatf.incoming.inspection")
        quality_score = 100.0
        ppm = 0.0
        if IQC is not None:
            iqcs = IQC.search([
                ("supplier_id", "=", supplier.id),
                ("state", "=", "decided"),
                ("inspection_date", ">=", period_start),
            ])
            total_qty = sum(iqcs.mapped("quantity_inspected"))
            rejected_qty = sum(iqcs.mapped("quantity_rejected"))
            if total_qty > 0:
                ppm = rejected_qty / total_qty * 1_000_000
                # PPM → 점수 변환: 0 PPM = 100점, 10000+ PPM = 0점
                quality_score = max(0, 100 - (ppm / 100))

        # ── 납기 점수: PO 납기 준수율 ──
        PO = self.env["purchase.order"]
        delivery_score = 100.0
        otd_pct = 100.0
        pos = PO.search([
            ("partner_id", "=", supplier.id),
            ("state", "in", ("purchase", "done")),
            ("date_order", ">=", period_start),
        ])
        if pos:
            pickings = self.env["stock.picking"].search([
                ("origin", "in", pos.mapped("name")),
                ("state", "=", "done"),
                ("picking_type_code", "=", "incoming"),
            ])
            if pickings:
                on_time = pickings.filtered(
                    lambda p: p.date_done and p.scheduled_date and p.date_done <= p.scheduled_date)
                otd_pct = len(on_time) / len(pickings) * 100
                delivery_score = otd_pct

        # ── 대응력 점수: SCAR 건수 & 대응 속도 ──
        SCAR = self.env.get("iatf.scar")
        responsiveness_score = 100.0
        scar_count = 0
        if SCAR is not None:
            scars = SCAR.search([
                ("supplier_id", "=", supplier.id),
                ("create_date", ">=", period_start),
            ])
            scar_count = len(scars)
            # SCAR 건당 -15점
            responsiveness_score = max(0, 100 - scar_count * 15)
            # 기한 초과 SCAR 추가 감점
            overdue = scars.filtered(
                lambda s: s.state not in ("closed", "verified") and s.due_date and s.due_date < today)
            responsiveness_score = max(0, responsiveness_score - len(overdue) * 10)

        # ── NC 건수 ──
        NC = self.env.get("iatf.nonconformity")
        nc_count = 0
        if NC is not None:
            nc_count = NC.search_count([
                ("partner_id", "=", supplier.id),
                ("detection_date", ">=", period_start),
            ])

        self.write({
            "score_quality": min(100, quality_score),
            "score_delivery": min(100, delivery_score),
            "score_responsiveness": min(100, responsiveness_score),
            "ppm_rate": ppm,
            "on_time_delivery_pct": otd_pct,
            "nc_count_period": nc_count,
            "scar_count_period": scar_count,
        })
        self.message_post(body=_(
            "업체 자동 채점 완료\n"
            "품질: %.1f점 (PPM: %.0f)\n"
            "납기: %.1f점 (준수율: %.1f%%)\n"
            "대응력: %.1f점 (SCAR: %d건)\n"
            "NC: %d건"
        ) % (quality_score, ppm, delivery_score, otd_pct,
             responsiveness_score, scar_count, nc_count))

    @api.model
    def _cron_auto_score_all(self):
        """분기 업체 자동 채점 cron (L5-3) — 기존 draft 평가 자동 채점"""
        evals = self.search([("state", "=", "draft")])
        for ev in evals:
            try:
                ev.action_auto_score()
            except Exception as e:
                ev.message_post(body=_("업체 자동 채점 오류: %s") % str(e))

    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_close(self):
        self.write({"state": "closed"})
