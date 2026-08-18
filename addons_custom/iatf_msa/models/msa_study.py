from odoo import api, fields, models, _
from odoo.exceptions import UserError
import math


class IatfMsaStudy(models.Model):
    _name = "iatf.msa.study"
    _description = "MSA Study — Gage R&R (IATF 16949 §7.1.5.1.1)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="MSA 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    study_date = fields.Date(string="연구일", default=fields.Date.today, tracking=True)
    product_id = fields.Many2one("product.product", string="제품 / 부품", tracking=True)
    study_type = fields.Selection(
        [
            ("grr_crossed", "Gage R&R (Crossed)"),
            ("grr_nested", "Gage R&R (Nested)"),
            ("bias", "Bias Study"),
            ("linearity", "Linearity Study"),
            ("stability", "Stability Study"),
        ],
        string="연구 유형", required=True, default="grr_crossed", tracking=True,
    )

    # ── Gage info ──
    instrument_id = fields.Many2one("iatf.measurement.equipment", string="측정 장비",
                                     help="교정관리 대상 측정장비 (회사양식 instrument)")
    gage_name = fields.Char(string="게이지 / 측정기명", required=True)
    gage_id_number = fields.Char(string="게이지 ID")
    gage_resolution = fields.Float(string="게이지 분해능", digits=(16, 6))

    # ── Characteristic ──
    characteristic_name = fields.Char(string="특성")
    unit = fields.Char(string="단위")
    specification = fields.Float(string="기준값 (nominal)", digits=(16, 4))
    usl = fields.Float(string="USL (상한)")
    lsl = fields.Float(string="LSL (하한)")
    tolerance = fields.Float(string="공차", compute="_compute_tolerance", store=True)

    # ── Study design ──
    num_operators = fields.Integer(string="측정자 수", default=3)
    num_parts = fields.Integer(string="부품 수", default=10)
    num_trials = fields.Integer(string="반복 횟수", default=3)

    # ── Measurements ──
    measurement_ids = fields.One2many("iatf.msa.measurement", "study_id", string="측정 데이터")
    measurement_count = fields.Integer(compute="_compute_measurement_count")

    # ── Results ──
    repeatability = fields.Float(string="반복성 (EV)", digits=(16, 6), readonly=True)
    reproducibility = fields.Float(string="재현성 (AV)", digits=(16, 6), readonly=True)
    grr = fields.Float(string="GRR (R&R)", digits=(16, 6), readonly=True)
    part_variation = fields.Float(string="부품 변동 (PV)", digits=(16, 6), readonly=True)
    total_variation = fields.Float(string="전체 변동 (TV)", digits=(16, 6), readonly=True)

    pct_ev = fields.Float(string="%EV", digits=(16, 2), readonly=True)
    pct_av = fields.Float(string="%AV", digits=(16, 2), readonly=True)
    pct_grr = fields.Float(string="%GRR", digits=(16, 2), readonly=True)
    pct_pv = fields.Float(string="%PV", digits=(16, 2), readonly=True)
    ndc = fields.Float(string="ndc (# Distinct Categories)", digits=(16, 1), readonly=True)

    grr_status = fields.Selection(
        [
            ("acceptable", "합격 (%GRR < 10%)"),
            ("marginal", "한계 (10% ≤ %GRR ≤ 30%)"),
            ("unacceptable", "불합격 (%GRR > 30%)"),
            ("not_calculated", "미산출"),
        ],
        string="GRR 상태", default="not_calculated", readonly=True,
    )

    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("collecting", "데이터 수집 중"),
            ("analyzed", "분석 완료"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
    )
    notes = fields.Text(string="비고 / 결론")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    # AIAG MSA K1 constants (by number of trials)
    K1_TABLE = {2: 0.8862, 3: 0.5908}
    # K2 constants (by number of operators)
    K2_TABLE = {2: 0.7071, 3: 0.5231}
    # K3 constants (by number of parts)
    K3_TABLE = {5: 0.4030, 10: 0.3146}

    @api.depends("usl", "lsl")
    def _compute_tolerance(self):
        for rec in self:
            rec.tolerance = rec.usl - rec.lsl if (rec.usl and rec.lsl) else 0.0

    @api.depends("measurement_ids")
    def _compute_measurement_count(self):
        for rec in self:
            rec.measurement_count = len(rec.measurement_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.msa.study") or _("New")
        return super().create(vals_list)

    def action_start_collecting(self):
        self.write({"state": "collecting"})

    def action_calculate(self):
        for study in self:
            study._calculate_grr()
        self.write({"state": "analyzed"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    @api.model
    def _cron_msa_schedule_alert(self):
        """주간 실행: 최근 1년간 MSA 미수행 게이지/특성 알림"""
        from datetime import timedelta
        one_year_ago = fields.Date.today() - timedelta(days=365)
        # 1년 이상 갱신 안된 closed 연구 → 재수행 필요
        old_studies = self.search([
            ("state", "=", "closed"),
            ("create_date", "<", one_year_ago),
        ])
        seen = set()
        for study in old_studies:
            key = (study.gage_name, study.characteristic_name)
            if key in seen:
                continue
            # 이후 최신 연구가 있으면 skip
            newer = self.search_count([
                ("gage_name", "=", study.gage_name),
                ("characteristic_name", "=", study.characteristic_name),
                ("create_date", ">=", one_year_ago),
            ])
            if newer:
                continue
            seen.add(key)
            study.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("MSA 재수행 필요: %s / %s (최근: %s)") % (
                    study.gage_name, study.characteristic_name,
                    study.create_date.strftime("%Y-%m-%d") if study.create_date else "-"),
                user_id=study.responsible_id.id or self.env.ref("base.user_admin").id,
            )

    def _calculate_grr(self):
        self.ensure_one()
        measurements = self.measurement_ids
        if not measurements:
            raise UserError(_("No measurements to analyze."))

        n_ops = self.num_operators or 3
        n_parts = self.num_parts or 10
        n_trials = self.num_trials or 3

        # Group by operator
        operators = list(set(measurements.mapped("operator_id.id")))
        parts = list(set(measurements.mapped("part_number")))

        if len(operators) < 2 or len(parts) < 2:
            raise UserError(_("Need at least 2 operators and 2 parts for GRR study."))

        # Calculate ranges per operator per part
        op_ranges = {}
        op_means = {}
        part_means = {}

        for op in operators:
            op_ranges[op] = []
            op_vals = []
            for part in parts:
                m = measurements.filtered(
                    lambda r: r.operator_id.id == op and r.part_number == part
                )
                vals = m.mapped("measured_value")
                if vals:
                    op_ranges[op].append(max(vals) - min(vals))
                    op_vals.extend(vals)
            op_means[op] = sum(op_vals) / len(op_vals) if op_vals else 0.0

        for part in parts:
            m = measurements.filtered(lambda r: r.part_number == part)
            vals = m.mapped("measured_value")
            part_means[part] = sum(vals) / len(vals) if vals else 0.0

        # Average range per operator, then overall R-bar
        r_bar_per_op = {op: (sum(rng) / len(rng) if rng else 0.0) for op, rng in op_ranges.items()}
        r_bar = sum(r_bar_per_op.values()) / len(r_bar_per_op) if r_bar_per_op else 0.0

        # Range of operator means
        x_diff = max(op_means.values()) - min(op_means.values()) if op_means else 0.0

        # Range of part means
        rp = max(part_means.values()) - min(part_means.values()) if part_means else 0.0

        k1 = self.K1_TABLE.get(n_trials, 0.5908)
        k2 = self.K2_TABLE.get(n_ops, 0.5231)
        k3 = self.K3_TABLE.get(n_parts, 0.3146)

        ev = r_bar * k1  # Repeatability
        av_sq = (x_diff * k2) ** 2 - (ev ** 2 / (n_parts * n_trials))
        av = math.sqrt(max(av_sq, 0.0))  # Reproducibility
        grr_val = math.sqrt(ev ** 2 + av ** 2)
        pv = rp * k3  # Part Variation
        tv = math.sqrt(grr_val ** 2 + pv ** 2)

        pct_ev_val = (ev / tv * 100.0) if tv else 0.0
        pct_av_val = (av / tv * 100.0) if tv else 0.0
        pct_grr_val = (grr_val / tv * 100.0) if tv else 0.0
        pct_pv_val = (pv / tv * 100.0) if tv else 0.0
        ndc_val = 1.41 * (pv / grr_val) if grr_val else 0.0

        if pct_grr_val < 10:
            status = "acceptable"
        elif pct_grr_val <= 30:
            status = "marginal"
        else:
            status = "unacceptable"

        self.write({
            "repeatability": ev,
            "reproducibility": av,
            "grr": grr_val,
            "part_variation": pv,
            "total_variation": tv,
            "pct_ev": pct_ev_val,
            "pct_av": pct_av_val,
            "pct_grr": pct_grr_val,
            "pct_pv": pct_pv_val,
            "ndc": ndc_val,
            "grr_status": status,
        })
