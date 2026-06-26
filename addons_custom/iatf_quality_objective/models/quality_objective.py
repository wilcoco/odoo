from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfQualityObjective(models.Model):
    _name = "iatf.quality.objective"
    _description = "품질 목표 (IATF 16949 §6.2)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "year desc, sequence"

    name = fields.Char(
        string="목표 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="목표명", required=True, tracking=True)
    year = fields.Char(string="대상 연도", required=True, default=lambda self: str(fields.Date.today().year))
    category = fields.Selection(
        [
            ("customer", "고객 만족"),
            ("quality", "품질 성과"),
            ("delivery", "납기 성과"),
            ("cost", "비용 / COPQ"),
            ("process", "공정 성과"),
            ("safety", "안전/환경"),
            ("supplier", "협력업체 품질"),
            ("other", "기타"),
        ],
        string="카테고리", required=True, default="quality", tracking=True,
    )
    description = fields.Html(string="목표 설명")
    sequence = fields.Integer(default=10)

    # ── KPI 정의 ──
    kpi_name = fields.Char(string="KPI 지표명", required=True)
    kpi_unit = fields.Char(string="단위", help="예: %, PPM, 건, 점")
    baseline_value = fields.Float(string="기준값 (전년도)")
    target_value = fields.Float(string="목표값", required=True)
    stretch_target = fields.Float(string="도전 목표값")

    # ── 실적 ──
    actual_q1 = fields.Float(string="1분기 실적")
    actual_q2 = fields.Float(string="2분기 실적")
    actual_q3 = fields.Float(string="3분기 실적")
    actual_q4 = fields.Float(string="4분기 실적")
    actual_ytd = fields.Float(string="연간 누적", compute="_compute_ytd", store=True)
    achievement_rate = fields.Float(string="달성률 (%)", compute="_compute_achievement", store=True)

    # ── 방향 ──
    direction = fields.Selection(
        [("higher", "높을수록 좋음"), ("lower", "낮을수록 좋음")],
        string="방향", default="higher", required=True,
    )
    achievement_status = fields.Selection(
        [
            ("on_track", "달성 중"),
            ("at_risk", "위험"),
            ("behind", "미달"),
            ("achieved", "달성"),
        ],
        string="달성 현황", compute="_compute_achievement", store=True,
    )

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    department_id = fields.Many2one("hr.department", string="부서")

    # ── 조치 계획 ──
    action_plan = fields.Html(string="실행 계획")
    review_notes = fields.Html(string="검토 기록")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("active", "활성"),
            ("review", "검토 중"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("actual_q1", "actual_q2", "actual_q3", "actual_q4")
    def _compute_ytd(self):
        for rec in self:
            values = [v for v in [rec.actual_q1, rec.actual_q2, rec.actual_q3, rec.actual_q4] if v]
            rec.actual_ytd = sum(values) / len(values) if values else 0.0

    @api.depends("actual_ytd", "target_value", "direction")
    def _compute_achievement(self):
        for rec in self:
            if rec.target_value:
                rec.achievement_rate = (rec.actual_ytd / rec.target_value) * 100.0
            else:
                rec.achievement_rate = 0.0

            if not rec.actual_ytd:
                rec.achievement_status = "behind"
            elif rec.direction == "higher":
                if rec.actual_ytd >= rec.target_value:
                    rec.achievement_status = "achieved"
                elif rec.actual_ytd >= rec.target_value * 0.9:
                    rec.achievement_status = "on_track"
                elif rec.actual_ytd >= rec.target_value * 0.7:
                    rec.achievement_status = "at_risk"
                else:
                    rec.achievement_status = "behind"
            else:  # lower is better
                if rec.actual_ytd <= rec.target_value:
                    rec.achievement_status = "achieved"
                elif rec.actual_ytd <= rec.target_value * 1.1:
                    rec.achievement_status = "on_track"
                elif rec.actual_ytd <= rec.target_value * 1.3:
                    rec.achievement_status = "at_risk"
                else:
                    rec.achievement_status = "behind"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.quality.objective") or _("New")
        return super().create(vals_list)

    def action_auto_calculate_kpi(self):
        """KPI 자동 계산: 각 모듈에서 실적 데이터 수집 (L5-1)"""
        self.ensure_one()
        from datetime import date
        year = int(self.year) if self.year.isdigit() else date.today().year
        quarter_ranges = {
            1: (date(year, 1, 1), date(year, 3, 31)),
            2: (date(year, 4, 1), date(year, 6, 30)),
            3: (date(year, 7, 1), date(year, 9, 30)),
            4: (date(year, 10, 1), date(year, 12, 31)),
        }
        values = {}
        kpi = self.kpi_name.lower() if self.kpi_name else ""

        for q, (start, end) in quarter_ranges.items():
            val = 0.0
            if "ppm" in kpi:
                val = self._calc_ppm(start, end)
            elif "납기" in kpi or "delivery" in kpi.lower():
                val = self._calc_otd(start, end)
            elif "cpk" in kpi:
                val = self._calc_avg_cpk()
            elif "합격률" in kpi or "pass" in kpi.lower():
                val = self._calc_inspection_pass_rate(start, end)
            elif "부적합" in kpi or "nc" in kpi.lower():
                val = self._calc_nc_count(start, end)
            elif "고객불만" in kpi or "complaint" in kpi.lower():
                val = self._calc_complaints(start, end)
            elif "copq" in kpi or "불량비용" in kpi:
                val = self._calc_copq(start, end)
            values[q] = val

        self.write({
            "actual_q1": values.get(1, 0),
            "actual_q2": values.get(2, 0),
            "actual_q3": values.get(3, 0),
            "actual_q4": values.get(4, 0),
        })
        self.message_post(body=_("KPI 자동 계산 완료"))

    def _model(self, name):
        """모델 미설치 시 None 반환. (빈 recordset 은 falsy 라 'if env.get()' 가 항상 거짓이
        되는 버그 방지 — 존재여부는 반드시 'name in self.env' 로 판정)"""
        return self.env[name] if name in self.env else None

    def _calc_ppm(self, start, end):
        """불량 PPM 계산"""
        total_qty = rejected_qty = 0.0
        for name in ("iatf.incoming.inspection", "iatf.process.inspection"):
            M = self._model(name)
            if M is None:
                continue
            recs = M.search([("inspection_date", ">=", start), ("inspection_date", "<=", end), ("state", "=", "decided")])
            total_qty += sum(recs.mapped("quantity_inspected"))
            rejected_qty += sum(recs.mapped("quantity_rejected"))
        return (rejected_qty / total_qty * 1000000) if total_qty else 0.0

    def _calc_otd(self, start, end):
        """납기 준수율 (%) — 출하 전표 기준"""
        pickings = self.env["stock.picking"].search([
            ("picking_type_code", "=", "outgoing"),
            ("state", "=", "done"),
            ("date_done", ">=", start),
            ("date_done", "<=", end),
        ])
        if not pickings:
            return 0.0
        on_time = pickings.filtered(lambda p: p.date_done and p.scheduled_date and p.date_done <= p.scheduled_date)
        return len(on_time) / len(pickings) * 100.0

    def _calc_avg_cpk(self):
        """평균 Cpk"""
        SPC = self._model("iatf.spc.study")
        if SPC is None:
            return 0.0
        studies = SPC.search([("state", "=", "analyzed"), ("cpk", ">", 0)])
        return sum(studies.mapped("cpk")) / len(studies) if studies else 0.0

    def _calc_complaints(self, start, end):
        """고객불만 건수"""
        CC = self._model("iatf.customer.complaint")
        if CC is None:
            return 0.0
        return CC.search_count([("received_date", ">=", start), ("received_date", "<=", end)])

    def _calc_copq(self, start, end):
        """불량 비용 (COPQ)"""
        NC = self._model("iatf.nonconformity")
        if NC is None:
            return 0.0
        ncs = NC.search([("detection_date", ">=", start), ("detection_date", "<=", end)])
        return sum(ncs.mapped("cost_total"))

    def _calc_inspection_pass_rate(self, start, end):
        """검사 합격률 (%) — 수입+공정검사 (pass+conditional)/판정완료 (G5)"""
        passed = decided = 0
        for name in ("iatf.incoming.inspection", "iatf.process.inspection"):
            M = self._model(name)
            if M is None:
                continue
            base = [("inspection_date", ">=", start), ("inspection_date", "<=", end)]
            passed += M.search_count(base + [("result", "in", ("pass", "conditional"))])
            decided += M.search_count(base + [("result", "in", ("pass", "conditional", "fail"))])
        return (passed / decided * 100.0) if decided else 0.0

    def _calc_nc_count(self, start, end):
        """부적합 건수 (G5)"""
        NC = self._model("iatf.nonconformity")
        if NC is None:
            return 0.0
        return NC.search_count([("detection_date", ">=", start), ("detection_date", "<=", end)])

    @api.model
    def _cron_auto_calculate_all(self):
        """월간 KPI 자동 계산 cron (L5-3)"""
        objectives = self.search([("state", "=", "active")])
        for obj in objectives:
            try:
                obj.action_auto_calculate_kpi()
            except Exception as e:
                obj.message_post(body=_("KPI 자동 계산 오류: %s") % str(e))

    def action_activate(self):
        self.write({"state": "active"})

    def action_review(self):
        self.write({"state": "review"})

    def action_close(self):
        self.write({"state": "closed"})
