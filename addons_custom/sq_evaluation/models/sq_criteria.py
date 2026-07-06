from odoo import api, fields, models, _
from odoo.exceptions import UserError

# SQ 평가항목 evidence_source → (Odoo 모델, 라벨). 우리(캠스) 자사 데이터 조회용.
# IATF 모듈이 없으면 model in self.env 로 안전하게 스킵(하드의존 회피).
EVIDENCE_MAP = {
    "iqc": ("iatf.incoming.inspection", "수입검사"),
    "process_inspection": ("iatf.process.inspection", "공정/최종검사"),
    "msa": ("iatf.msa.study", "MSA (Gage R&R)"),
    "spc": ("iatf.spc.study", "SPC 공정능력"),
    "reliability": ("iatf.reliability.test", "신뢰성 시험"),
    "calibration": ("iatf.calibration.record", "계측기 교정"),
    "equipment": ("iatf.equipment", "설비 대장"),
    "mold": ("iatf.mold", "금형 대장"),
    "traceability": ("iatf.traceability.record", "LOT 추적성"),
    "control_plan": ("iatf.control.plan", "관리계획서/표준류"),
    "nc": ("iatf.nonconformity", "부적합/격리"),
    "quality_objective": ("iatf.quality.objective", "품질목표/실적"),
    "training": ("iatf.competence.matrix", "역량/자격인증"),
    "change_management": ("iatf.change.request", "설계변경/4M"),
    "jig": ("iatf.jig.record", "지그 점검 기록"),
    "document": ("iatf.document", "품질문서/매뉴얼"),
    "environment": ("iatf.environment.check", "작업환경(조도/온습도) 점검"),
    "inspection_criteria": ("iatf.inspection.criteria", "검사기준/한도견본"),
    "field_record": ("sq.field.record", "현장/절차 증빙 기록"),
    # ── IATF 심사 기준용 증빙 소스 ──
    "fmea": ("iatf.fmea", "FMEA"),
    "ppap": ("iatf.ppap.submission", "PPAP 제출"),
    "apqp": ("iatf.apqp.project", "APQP 프로젝트"),
    "audit": ("iatf.audit", "내부심사"),
    "management_review": ("iatf.management.review", "경영검토"),
    "complaint": ("iatf.customer.complaint", "고객불만"),
    "supplier_eval": ("iatf.supplier.evaluation", "공급자 평가"),
    "corrective_action": ("iatf.corrective.action", "시정조치(8D)"),
    "risk": ("iatf.risk.register", "리스크 관리"),
    "contingency": ("iatf.contingency.plan", "비상사태 대응계획"),
    "csr": ("iatf.csr", "고객특별요구사항(CSR)"),
    "layout_inspection": ("iatf.layout.inspection", "레이아웃(정기) 검사"),
    "customer_property": ("iatf.customer.property", "고객자산"),
    "packaging": ("iatf.packaging.spec", "포장 사양"),
    "outsource": ("iatf.outsource.order", "외주 관리"),
    # ── 사출 현장 실측(PLC/전용기록) — SQ L3 증빙 승격 ──
    "molding_condition": ("engel.injection.serial", "성형조건 실측(PLC: 사이클·압력·온도)"),
    "moisture": ("injection.rawmaterial.moisture", "원재료 수분 측정 기록"),
}

FRAMEWORK_SELECTION = [("sq", "SQ"), ("iatf", "IATF 16949")]
EVIDENCE_SELECTION = [(k, v[1]) for k, v in EVIDENCE_MAP.items()] + [("none", "연동 없음 (현장/수기 증빙)")]

# 소스별 기간 스코프용 날짜필드 (없으면 기간필터 생략)
EVIDENCE_DATE_FIELD = {
    "iqc": "inspection_date",
    "process_inspection": "inspection_date",
    "msa": "study_date",
    "spc": "analysis_date",
    "reliability": "test_date",
    "calibration": "calibration_date",
    "nc": "detection_date",
    "control_plan": "revision_date",
    "training": "last_training_date",
    "environment": "check_date",
    "document": "revision_date",
    "change_management": "request_date",
    "jig": "record_date",
    "field_record": "record_date",
    "complaint": "received_date",
    "audit": "actual_date",
    "corrective_action": "due_date",
}


class SqEvidenceMixin(models.AbstractModel):
    """평가항목/라인이 공유하는 증빙 조회 로직. evidence_source 필드는 상속 모델이 보유."""
    _name = "sq.evidence.mixin"
    _description = "SQ Evidence Resolver Mixin"

    evidence_count = fields.Integer(string="증빙 건수", compute="_compute_evidence_count")
    evidence_available = fields.Boolean(string="Odoo 연동 가능", compute="_compute_evidence_count")

    def _evidence_target(self):
        """(model_name, label) 반환. 미설치/미연동이면 (None, label)."""
        src = self.evidence_source
        model, label = EVIDENCE_MAP.get(src, (None, None))
        if model and model in self.env:
            return model, label
        # traceability 폴백: 전용 추적모델 없으면 표준 stock.lot
        if src == "traceability" and "stock.lot" in self.env:
            return "stock.lot", "LOT/시리얼 (stock.lot)"
        # 사출 실측 소스(PLC 등) 미설치 환경 → 현장/절차 점검기록으로 폴백
        if src in ("molding_condition", "moisture") and "sq.field.record" in self.env:
            return "sq.field.record", (label or "") + " (미설치 → 현장기록 폴백)"
        return None, label

    def _evidence_criteria_id(self):
        """이 레코드가 가리키는 sq.criteria id. (criteria=자기 자신, line=criteria_id)"""
        return self.id if self._name == "sq.criteria" else self.criteria_id.id

    def _evidence_domain(self):
        """자사 데이터 전체 (스코프=자가평가). 현장기록(폴백 포함)은 해당 기준으로 스코프."""
        model, _label = self._evidence_target()
        if model == "sq.field.record":
            return [("criteria_id", "=", self._evidence_criteria_id())]
        return []

    @api.depends("evidence_source")
    def _compute_evidence_count(self):
        for rec in self:
            model, _label = rec._evidence_target()
            if model:
                rec.evidence_available = True
                try:
                    rec.evidence_count = rec.env[model].search_count(rec._evidence_domain())
                except Exception:
                    rec.evidence_count = 0
            else:
                rec.evidence_available = False
                rec.evidence_count = 0

    def action_view_evidence(self):
        self.ensure_one()
        model, label = self._evidence_target()
        if not model:
            raise UserError(_("이 항목은 Odoo 연동 증빙이 없습니다 (현장/수기 증빙 대상)."))
        ctx = {}
        if model == "sq.field.record":
            # 드릴다운에서 바로 현장증빙 기록 추가 가능하도록 기준 프리필
            ctx = {"default_criteria_id": self._evidence_criteria_id()}
        return {
            "type": "ir.actions.act_window",
            "name": _("증빙자료: %s") % (label or model),
            "res_model": model,
            "view_mode": "list,form",
            "domain": self._evidence_domain(),
            "target": "current",
            "context": ctx,
        }


class SqCategory(models.Model):
    _name = "sq.category"
    _description = "SQ 평가 대분류"
    _order = "sequence, id"

    name = fields.Char(string="대분류", required=True)
    code = fields.Char(string="코드", required=True)
    framework = fields.Selection(FRAMEWORK_SELECTION, string="평가체계", default="sq", required=True)
    sequence = fields.Integer(default=10)
    criteria_ids = fields.One2many("sq.criteria", "category_id", string="세부항목")
    criteria_count = fields.Integer(compute="_compute_counts")
    max_score_total = fields.Integer(string="배점 합계", compute="_compute_counts")

    def _compute_counts(self):
        for rec in self:
            rec.criteria_count = len(rec.criteria_ids)
            rec.max_score_total = sum(rec.criteria_ids.mapped("max_score"))

    def action_open_criteria(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("증빙 대시보드: %s") % self.name,
            "res_model": "sq.criteria",
            "view_mode": "list,form",
            "domain": [("category_id", "=", self.id)],
            "context": {"default_category_id": self.id, "search_default_category_id": self.id},
        }


CHECK_CYCLE_SELECTION = [
    ("daily", "일"), ("shift", "교대시"), ("weekly", "주"), ("monthly", "월"),
    ("quarterly", "분기"), ("biannual", "반기"), ("annual", "년"),
    ("event", "발생시"), ("none", "해당없음"),
]
INPUT_TYPE_SELECTION = [
    ("pass_fail", "적합/부적합"), ("number", "수치"), ("text", "서술"),
]


class SqCriteria(models.Model):
    _name = "sq.criteria"
    _description = "SQ 평가 기준 항목 (템플릿)"
    _inherit = ["sq.evidence.mixin"]
    _order = "sequence, id"

    code = fields.Char(string="No", required=True)
    category_id = fields.Many2one("sq.category", string="대분류", required=True, ondelete="cascade")
    framework = fields.Selection(related="category_id.framework", store=True, string="평가체계")
    sequence = fields.Integer(default=10)
    name = fields.Char(string="세부항목", required=True)
    description = fields.Text(string="점검 상세")
    max_score = fields.Integer(string="배점", default=0)
    evidence_source = fields.Selection(EVIDENCE_SELECTION, string="증빙 출처", default="none", required=True)
    check_cycle = fields.Selection(CHECK_CYCLE_SELECTION, string="점검 주기", default="none",
                                   help="현장/절차 증빙(field_record) 항목의 점검 주기")
    checklist_ids = fields.One2many("sq.checklist.template", "criteria_id", string="점검서식(체크리스트)")
    checklist_count = fields.Integer(compute="_compute_checklist_count")
    active = fields.Boolean(default=True)

    def _compute_checklist_count(self):
        for rec in self:
            rec.checklist_count = len(rec.checklist_ids)

    def action_new_field_record(self):
        """이 항목의 주기 점검기록 신규 작성 (체크리스트 자동 로드)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("점검기록 작성: %s") % self.name,
            "res_model": "sq.field.record",
            "view_mode": "form",
            "target": "current",
            "context": {"default_criteria_id": self.id},
        }


class SqChecklistTemplate(models.Model):
    _name = "sq.checklist.template"
    _description = "SQ 점검서식 항목 (체크리스트 템플릿)"
    _order = "criteria_id, sequence, id"

    criteria_id = fields.Many2one("sq.criteria", string="SQ 평가항목", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(string="점검 항목", required=True)
    input_type = fields.Selection(INPUT_TYPE_SELECTION, string="입력 유형", default="pass_fail", required=True)
    spec = fields.Char(string="기준 / 규격")
    unit = fields.Char(string="단위")
