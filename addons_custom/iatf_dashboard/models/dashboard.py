from odoo import api, fields, models, _


class IatfDashboard(models.TransientModel):
    _name = "iatf.dashboard"
    _description = "IATF Quality Dashboard KPI"

    
    # ── Document Control ──
    doc_total = fields.Integer(compute="_compute_all")
    doc_pending_approval = fields.Integer(compute="_compute_all")

    # ── Nonconformity / 8D ──
    nc_open = fields.Integer(compute="_compute_all")
    nc_overdue = fields.Integer(compute="_compute_all")
    nc_total_ytd = fields.Integer(compute="_compute_all")

    # ── Customer Complaints ──
    complaint_open = fields.Integer(compute="_compute_all")
    complaint_critical = fields.Integer(compute="_compute_all")
    complaint_cost_ytd = fields.Float(compute="_compute_all")

    # ── FMEA ──
    fmea_high_risk = fields.Integer(compute="_compute_all")
    fmea_open_actions = fields.Integer(compute="_compute_all")

    # ── PPAP ──
    ppap_open = fields.Integer(compute="_compute_all")
    ppap_rejected = fields.Integer(compute="_compute_all")

    # ── SPC ──
    spc_not_capable = fields.Integer(compute="_compute_all")
    spc_ooc = fields.Integer(compute="_compute_all")

    # ── MSA ──
    msa_unacceptable = fields.Integer(compute="_compute_all")

    # ── Audit ──
    audit_open_findings = fields.Integer(compute="_compute_all")
    audit_planned = fields.Integer(compute="_compute_all")

    # ── Corrective Action (G4) ──
    ca_open = fields.Integer(compute="_compute_all")
    ca_overdue = fields.Integer(compute="_compute_all")

    # ── Supplier ──
    supplier_grade_d = fields.Integer(compute="_compute_all")
    scar_open = fields.Integer(compute="_compute_all")

    # ── Calibration ──
    cal_overdue = fields.Integer(compute="_compute_all")

    # ── Training ──
    training_gaps = fields.Integer(compute="_compute_all")

    # ── Risk ──
    risk_critical = fields.Integer(compute="_compute_all")
    risk_high = fields.Integer(compute="_compute_all")

    # ── APQP ──
    apqp_active = fields.Integer(compute="_compute_all")

    # ── Incoming Inspection ──
    iqc_open = fields.Integer(compute="_compute_all")
    iqc_fail = fields.Integer(compute="_compute_all")
    iqc_pass_rate = fields.Float(compute="_compute_all", string="IQC 합격률 (%)", digits=(5, 1))

    # ── Process Inspection ──
    pqc_open = fields.Integer(compute="_compute_all")
    pqc_fail = fields.Integer(compute="_compute_all")
    pqc_pass_rate = fields.Float(compute="_compute_all", string="공정검사 합격률 (%)", digits=(5, 1))

    # ── Quality Objective ──
    qo_active = fields.Integer(compute="_compute_all")
    qo_behind = fields.Integer(compute="_compute_all")

    # ── Change Management ──
    cr_open = fields.Integer(compute="_compute_all")
    cr_high_risk = fields.Integer(compute="_compute_all")

    # ── CSR ──
    csr_active = fields.Integer(compute="_compute_all")
    csr_non_compliant = fields.Integer(compute="_compute_all")

    # ── Layout Inspection ──
    li_open = fields.Integer(compute="_compute_all")
    li_fail = fields.Integer(compute="_compute_all")

    # ── Equipment / TPM ──
    eq_active = fields.Integer(compute="_compute_all")
    eq_breakdown = fields.Integer(compute="_compute_all")
    eq_pm_overdue = fields.Integer(compute="_compute_all")

    # ── Mold ──
    mold_active = fields.Integer(compute="_compute_all")
    mold_life_warning = fields.Integer(compute="_compute_all")

    # ── Customer Property ──
    cp_active = fields.Integer(compute="_compute_all")
    cp_issue = fields.Integer(compute="_compute_all")

    # ── Outsource ──
    os_open = fields.Integer(compute="_compute_all")
    os_fail = fields.Integer(compute="_compute_all")

    def _safe_count(self, model, domain):
        """search_count that returns 0 if model is not installed."""
        try:
            return self.env[model].search_count(domain)
        except KeyError:
            return 0

    def _safe_search(self, model, domain):
        """search that returns empty recordset if model is not installed."""
        try:
            return self.env[model].search(domain)
        except KeyError:
            return self.env["base"].browse()

    def _pass_rate(self, model):
        """합격률(%) = (pass+conditional) / 판정완료 건수 × 100. 모델 없거나 0건이면 0.0."""
        passed = self._safe_count(model, [("result", "in", ("pass", "conditional"))])
        decided = self._safe_count(model, [("result", "in", ("pass", "conditional", "fail"))])
        return round(passed / decided * 100.0, 1) if decided else 0.0

    def _compute_all(self):
        today = fields.Date.today()
        year_start = today.replace(month=1, day=1)
        sc = self._safe_count
        ss = self._safe_search

        for rec in self:
            # Document Control
            rec.doc_total = sc("iatf.document", [])
            rec.doc_pending_approval = sc("iatf.document",
                [("state", "=", "review")])

            # NC
            rec.nc_open = sc("iatf.nonconformity",
                [("state", "not in", ("closed", "cancelled"))])
            rec.nc_overdue = sc("iatf.nonconformity",
                [("state", "not in", ("closed", "cancelled")),
                 ("target_close_date", "<", today)])
            rec.nc_total_ytd = sc("iatf.nonconformity",
                [("create_date", ">=", year_start)])

            # Customer Complaints
            rec.complaint_open = sc("iatf.customer.complaint",
                [("state", "!=", "closed")])
            rec.complaint_critical = sc("iatf.customer.complaint",
                [("severity_level", "=", "critical"), ("state", "!=", "closed")])
            complaints_ytd = ss("iatf.customer.complaint",
                [("create_date", ">=", year_start)])
            rec.complaint_cost_ytd = sum(complaints_ytd.mapped("cost_total")) if complaints_ytd else 0

            # FMEA
            rec.fmea_high_risk = sc("iatf.fmea.line",
                [("action_priority", "=", "high")])
            rec.fmea_open_actions = sc("iatf.fmea.line",
                [("action_status", "in", ("open", "in_progress"))])

            # PPAP
            rec.ppap_open = sc("iatf.ppap.submission",
                [("state", "not in", ("closed",))])
            rec.ppap_rejected = sc("iatf.ppap.submission",
                [("customer_decision", "=", "rejected")])

            # SPC
            rec.spc_not_capable = sc("iatf.spc.study",
                [("capability_status", "=", "not_capable")])
            rec.spc_ooc = sc("iatf.spc.study",
                [("ooc_count", ">", 0)])

            # MSA
            rec.msa_unacceptable = sc("iatf.msa.study",
                [("grr_status", "=", "unacceptable")])

            # Audit
            rec.audit_open_findings = sc("iatf.audit.finding",
                [("state", "!=", "closed")])
            rec.audit_planned = sc("iatf.audit",
                [("state", "=", "planned")])

            # Corrective Action (G4)
            rec.ca_open = sc("iatf.corrective.action",
                [("state", "not in", ("verified", "closed"))])
            rec.ca_overdue = sc("iatf.corrective.action",
                [("is_overdue", "=", True)])

            # Supplier
            rec.supplier_grade_d = sc("iatf.supplier.evaluation",
                [("grade", "=", "d"), ("state", "=", "confirmed")])
            rec.scar_open = sc("iatf.scar",
                [("state", "not in", ("closed",))])

            # Calibration
            rec.cal_overdue = sc("iatf.measurement.equipment",
                [("is_overdue", "=", True), ("state", "=", "active")])

            # Training
            rec.training_gaps = sc("iatf.competence.matrix",
                [("gap", "=", True)])

            # Risk
            rec.risk_critical = sc("iatf.risk.register",
                [("risk_level", "=", "critical"), ("state", "!=", "closed")])
            rec.risk_high = sc("iatf.risk.register",
                [("risk_level", "=", "high"), ("state", "!=", "closed")])

            # APQP
            rec.apqp_active = sc("iatf.apqp.project",
                [("state", "=", "active")])

            # Incoming Inspection
            rec.iqc_open = sc("iatf.incoming.inspection",
                [("state", "not in", ("closed", "cancelled"))])
            rec.iqc_fail = sc("iatf.incoming.inspection",
                [("result", "=", "fail")])
            rec.iqc_pass_rate = self._pass_rate("iatf.incoming.inspection")

            # Process Inspection
            rec.pqc_open = sc("iatf.process.inspection",
                [("state", "not in", ("closed", "cancelled"))])
            rec.pqc_fail = sc("iatf.process.inspection",
                [("result", "=", "fail")])
            rec.pqc_pass_rate = self._pass_rate("iatf.process.inspection")

            # Quality Objective
            rec.qo_active = sc("iatf.quality.objective",
                [("state", "=", "active")])
            rec.qo_behind = sc("iatf.quality.objective",
                [("achievement_status", "in", ("behind", "at_risk")), ("state", "=", "active")])

            # Change Management
            rec.cr_open = sc("iatf.change.request",
                [("state", "not in", ("closed", "rejected"))])
            rec.cr_high_risk = sc("iatf.change.request",
                [("risk_level", "in", ("high", "critical")), ("state", "not in", ("closed", "rejected"))])

            # CSR
            rec.csr_active = sc("iatf.csr",
                [("state", "=", "active")])
            rec.csr_non_compliant = sc("iatf.csr",
                [("compliance_status", "in", ("non_compliant", "partial")), ("state", "=", "active")])

            # Layout Inspection
            rec.li_open = sc("iatf.layout.inspection",
                [("state", "not in", ("closed",))])
            rec.li_fail = sc("iatf.layout.inspection",
                [("result", "=", "fail")])

            # Equipment / TPM
            # 설비 대장은 공장/라인/설비/장치를 한 테이블에 담는다. 타일이 말하는 '설비 수'는
            # 설비 단위이므로 장치(DV-)·라인·공장은 세지 않는다. 이 필터가 없으면 장치를
            # 등록하기 시작하는 순간 가동 설비 수가 부풀어 오른다.
            rec.eq_active = sc("iatf.equipment",
                [("node_type", "=", "equipment"), ("state", "=", "active")])
            rec.eq_breakdown = sc("iatf.equipment",
                [("node_type", "=", "equipment"), ("state", "=", "breakdown")])
            rec.eq_pm_overdue = sc("iatf.equipment",
                [("node_type", "=", "equipment"),
                 ("is_pm_overdue", "=", True), ("state", "=", "active")])

            # Mold
            rec.mold_active = sc("iatf.mold",
                [("state", "=", "active")])
            rec.mold_life_warning = sc("iatf.mold",
                [("life_percentage", ">=", 80), ("state", "=", "active")])

            # Customer Property
            rec.cp_active = sc("iatf.customer.property",
                [("state", "=", "active")])
            rec.cp_issue = sc("iatf.customer.property",
                [("current_condition", "in", ("damaged", "lost")), ("state", "=", "active")])

            # Outsource
            rec.os_open = sc("iatf.outsource.order",
                [("state", "not in", ("closed",))])
            rec.os_fail = sc("iatf.outsource.order",
                [("inspection_result", "=", "fail")])

    def action_refresh(self):
        """Create a fresh transient record and reopen the dashboard."""
        new = self.create({})
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.dashboard",
            "res_id": new.id,
            "view_mode": "form",
            "target": "inline",
        }

    def action_open_nc_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.nonconformity",
                "view_mode": "list,form", "name": _("Open Nonconformities"),
                "domain": [("state", "not in", ("closed", "cancelled"))]}

    def action_open_complaints(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.customer.complaint",
                "view_mode": "list,form", "name": _("Open Complaints"),
                "domain": [("state", "!=", "closed")]}

    def action_open_ca_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.corrective.action",
                "view_mode": "list,form", "name": _("진행 중 시정조치"),
                "domain": [("state", "not in", ("verified", "closed"))]}

    def action_open_fmea_high(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.fmea.line",
                "view_mode": "list,form", "name": _("High Risk Failure Modes"),
                "domain": [("action_priority", "=", "high")]}

    def action_open_spc_not_capable(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.spc.study",
                "view_mode": "list,form", "name": _("Not Capable SPC Studies"),
                "domain": [("capability_status", "=", "not_capable")]}

    def action_open_cal_overdue(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.measurement.equipment",
                "view_mode": "list,form", "name": _("Overdue Calibrations"),
                "domain": [("is_overdue", "=", True), ("state", "=", "active")]}

    def action_open_training_gaps(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.competence.matrix",
                "view_mode": "list", "name": _("Competence Gaps"),
                "domain": [("gap", "=", True)]}

    def action_open_audit_findings(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.audit.finding",
                "view_mode": "list,form", "name": _("Open Audit Findings"),
                "domain": [("state", "!=", "closed")]}

    def action_open_risk_critical(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.risk.register",
                "view_mode": "list,form", "name": _("Critical & High Risks"),
                "domain": [("risk_level", "in", ("critical", "high")), ("state", "!=", "closed")]}

    def action_open_scar_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.scar",
                "view_mode": "list,form", "name": _("Open SCARs"),
                "domain": [("state", "not in", ("closed",))]}

    def action_open_ppap_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.ppap.submission",
                "view_mode": "list,form", "name": _("Open PPAP Submissions"),
                "domain": [("state", "not in", ("closed",))]}

    def action_open_msa_unacceptable(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.msa.study",
                "view_mode": "list,form", "name": _("Unacceptable MSA Studies"),
                "domain": [("grr_status", "=", "unacceptable")]}

    def action_open_iqc_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.incoming.inspection",
                "view_mode": "list,form", "name": _("수입검사 진행 중"),
                "domain": [("state", "not in", ("closed", "cancelled"))]}

    def action_open_pqc_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.process.inspection",
                "view_mode": "list,form", "name": _("공정검사 진행 중"),
                "domain": [("state", "not in", ("closed", "cancelled"))]}

    def action_open_qo_behind(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.quality.objective",
                "view_mode": "list,form", "name": _("품질 목표 미달/위험"),
                "domain": [("achievement_status", "in", ("behind", "at_risk")), ("state", "=", "active")]}

    def action_open_cr_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.change.request",
                "view_mode": "list,form", "name": _("변경 요청 진행 중"),
                "domain": [("state", "not in", ("closed", "rejected"))]}

    def action_open_csr_noncompliant(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.csr",
                "view_mode": "list,form", "name": _("CSR 부적합/부분적합"),
                "domain": [("compliance_status", "in", ("non_compliant", "partial")), ("state", "=", "active")]}

    def action_open_li_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.layout.inspection",
                "view_mode": "list,form", "name": _("레이아웃 검사 진행 중"),
                "domain": [("state", "not in", ("closed",))]}

    def action_open_eq_breakdown(self):
        # 타일 숫자와 목록이 어긋나지 않도록 집계와 같은 설비 단위 필터를 건다.
        return {"type": "ir.actions.act_window", "res_model": "iatf.equipment",
                "view_mode": "list,form", "name": _("설비 고장/PM 초과"),
                "domain": [("node_type", "=", "equipment"),
                           '|', ("state", "=", "breakdown"), ("is_pm_overdue", "=", True)]}

    def action_open_mold_warning(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.mold",
                "view_mode": "list,form", "name": _("금형 수명 경고"),
                "domain": [("life_percentage", ">=", 80), ("state", "=", "active")]}

    def action_open_cp_issue(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.customer.property",
                "view_mode": "list,form", "name": _("고객재산 이상"),
                "domain": [("current_condition", "in", ("damaged", "lost")), ("state", "=", "active")]}

    def action_open_os_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.outsource.order",
                "view_mode": "list,form", "name": _("외주 진행 중"),
                "domain": [("state", "not in", ("closed",))]}
