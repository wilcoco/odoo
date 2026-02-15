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

    # ── Process Inspection ──
    pqc_open = fields.Integer(compute="_compute_all")
    pqc_fail = fields.Integer(compute="_compute_all")

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

    def _compute_all(self):
        today = fields.Date.today()
        year_start = today.replace(month=1, day=1)

        for rec in self:
            # Document Control
            docs = self.env["iatf.document"].search([])
            rec.doc_total = len(docs)
            rec.doc_pending_approval = self.env["iatf.document"].search_count(
                [("state", "=", "review")])

            # NC
            rec.nc_open = self.env["iatf.nonconformity"].search_count(
                [("state", "not in", ("closed", "cancelled"))])
            rec.nc_overdue = self.env["iatf.nonconformity"].search_count(
                [("state", "not in", ("closed", "cancelled")),
                 ("target_close_date", "<", today)])
            rec.nc_total_ytd = self.env["iatf.nonconformity"].search_count(
                [("create_date", ">=", year_start)])

            # Customer Complaints
            rec.complaint_open = self.env["iatf.customer.complaint"].search_count(
                [("state", "!=", "closed")])
            rec.complaint_critical = self.env["iatf.customer.complaint"].search_count(
                [("severity_level", "=", "critical"), ("state", "!=", "closed")])
            complaints_ytd = self.env["iatf.customer.complaint"].search(
                [("create_date", ">=", year_start)])
            rec.complaint_cost_ytd = sum(complaints_ytd.mapped("cost_total"))

            # FMEA
            rec.fmea_high_risk = self.env["iatf.fmea.line"].search_count(
                [("action_priority", "=", "high")])
            rec.fmea_open_actions = self.env["iatf.fmea.line"].search_count(
                [("action_status", "in", ("open", "in_progress"))])

            # PPAP
            rec.ppap_open = self.env["iatf.ppap.submission"].search_count(
                [("state", "not in", ("closed",))])
            rec.ppap_rejected = self.env["iatf.ppap.submission"].search_count(
                [("customer_decision", "=", "rejected")])

            # SPC
            rec.spc_not_capable = self.env["iatf.spc.study"].search_count(
                [("capability_status", "=", "not_capable")])
            rec.spc_ooc = self.env["iatf.spc.study"].search_count(
                [("ooc_count", ">", 0)])

            # MSA
            rec.msa_unacceptable = self.env["iatf.msa.study"].search_count(
                [("grr_status", "=", "unacceptable")])

            # Audit
            rec.audit_open_findings = self.env["iatf.audit.finding"].search_count(
                [("state", "!=", "closed")])
            rec.audit_planned = self.env["iatf.audit"].search_count(
                [("state", "=", "planned")])

            # Supplier
            rec.supplier_grade_d = self.env["iatf.supplier.evaluation"].search_count(
                [("grade", "=", "d"), ("state", "=", "confirmed")])
            rec.scar_open = self.env["iatf.scar"].search_count(
                [("state", "not in", ("closed",))])

            # Calibration
            rec.cal_overdue = self.env["iatf.measurement.equipment"].search_count(
                [("is_overdue", "=", True), ("state", "=", "active")])

            # Training
            rec.training_gaps = self.env["iatf.competence.matrix"].search_count(
                [("gap", "=", True)])

            # Risk
            rec.risk_critical = self.env["iatf.risk.register"].search_count(
                [("risk_level", "=", "critical"), ("state", "!=", "closed")])
            rec.risk_high = self.env["iatf.risk.register"].search_count(
                [("risk_level", "=", "high"), ("state", "!=", "closed")])

            # APQP
            rec.apqp_active = self.env["iatf.apqp.project"].search_count(
                [("state", "=", "active")])

            # Incoming Inspection
            rec.iqc_open = self.env["iatf.incoming.inspection"].search_count(
                [("state", "not in", ("closed", "cancelled"))])
            rec.iqc_fail = self.env["iatf.incoming.inspection"].search_count(
                [("result", "=", "fail")])

            # Process Inspection
            rec.pqc_open = self.env["iatf.process.inspection"].search_count(
                [("state", "not in", ("closed", "cancelled"))])
            rec.pqc_fail = self.env["iatf.process.inspection"].search_count(
                [("result", "=", "fail")])

            # Quality Objective
            rec.qo_active = self.env["iatf.quality.objective"].search_count(
                [("state", "=", "active")])
            rec.qo_behind = self.env["iatf.quality.objective"].search_count(
                [("achievement_status", "in", ("behind", "at_risk")), ("state", "=", "active")])

            # Change Management
            rec.cr_open = self.env["iatf.change.request"].search_count(
                [("state", "not in", ("closed", "rejected"))])
            rec.cr_high_risk = self.env["iatf.change.request"].search_count(
                [("risk_level", "in", ("high", "critical")), ("state", "not in", ("closed", "rejected"))])

            # CSR
            rec.csr_active = self.env["iatf.csr"].search_count(
                [("state", "=", "active")])
            rec.csr_non_compliant = self.env["iatf.csr"].search_count(
                [("compliance_status", "in", ("non_compliant", "partial")), ("state", "=", "active")])

            # Layout Inspection
            rec.li_open = self.env["iatf.layout.inspection"].search_count(
                [("state", "not in", ("closed",))])
            rec.li_fail = self.env["iatf.layout.inspection"].search_count(
                [("result", "=", "fail")])

            # Equipment / TPM
            rec.eq_active = self.env["iatf.equipment"].search_count(
                [("state", "=", "active")])
            rec.eq_breakdown = self.env["iatf.equipment"].search_count(
                [("state", "=", "breakdown")])
            rec.eq_pm_overdue = self.env["iatf.equipment"].search_count(
                [("is_pm_overdue", "=", True), ("state", "=", "active")])

            # Mold
            rec.mold_active = self.env["iatf.mold"].search_count(
                [("state", "=", "active")])
            rec.mold_life_warning = self.env["iatf.mold"].search_count(
                [("life_percentage", ">=", 80), ("state", "=", "active")])

            # Customer Property
            rec.cp_active = self.env["iatf.customer.property"].search_count(
                [("state", "=", "active")])
            rec.cp_issue = self.env["iatf.customer.property"].search_count(
                [("current_condition", "in", ("damaged", "lost")), ("state", "=", "active")])

            # Outsource
            rec.os_open = self.env["iatf.outsource.order"].search_count(
                [("state", "not in", ("closed",))])
            rec.os_fail = self.env["iatf.outsource.order"].search_count(
                [("inspection_result", "=", "fail")])

    def action_open_nc_open(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.nonconformity",
                "view_mode": "list,form", "name": _("Open Nonconformities"),
                "domain": [("state", "not in", ("closed", "cancelled"))]}

    def action_open_complaints(self):
        return {"type": "ir.actions.act_window", "res_model": "iatf.customer.complaint",
                "view_mode": "list,form", "name": _("Open Complaints"),
                "domain": [("state", "!=", "closed")]}

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
        return {"type": "ir.actions.act_window", "res_model": "iatf.equipment",
                "view_mode": "list,form", "name": _("설비 고장/PM 초과"),
                "domain": ['|', ("state", "=", "breakdown"), ("is_pm_overdue", "=", True)]}

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
