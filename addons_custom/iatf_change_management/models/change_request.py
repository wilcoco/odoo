from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfChangeRequest(models.Model):
    _name = "iatf.change.request"
    _description = "4M 변경 관리 (IATF 16949 §8.5.6)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="변경 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="변경 제목", required=True, tracking=True)

    change_type = fields.Selection(
        [
            ("man", "Man (인원 변경)"),
            ("machine", "Machine (설비 변경)"),
            ("material", "Material (자재 변경)"),
            ("method", "Method (방법/공정 변경)"),
            ("environment", "Environment (환경 변경)"),
        ],
        string="변경 유형 (4M+E)", required=True, tracking=True,
    )
    change_category = fields.Selection(
        [
            ("planned", "계획된 변경"),
            ("unplanned", "비계획 변경 (긴급)"),
            ("temporary", "임시 변경"),
            ("permanent", "영구 변경"),
        ],
        string="변경 구분", required=True, default="planned", tracking=True,
    )
    change_source = fields.Selection(
        [
            ("internal", "내부 변경"),
            ("customer", "고객 요청"),
            ("supplier", "협력업체 변경"),
            ("regulatory", "법규/규격 변경"),
            ("engineering", "설계 변경"),
        ],
        string="변경 원인", default="internal", tracking=True,
    )

    # ── 변경 상세 ──
    description = fields.Html(string="변경 내용", required=True)
    reason = fields.Html(string="변경 사유", required=True)
    affected_product_ids = fields.Many2many("product.product", string="영향 제품")
    affected_process = fields.Char(string="영향 공정")
    affected_department_ids = fields.Many2many("hr.department", string="영향 부서")

    # ── 변경 전후 ──
    before_state = fields.Html(string="변경 전 상태")
    after_state = fields.Html(string="변경 후 상태")

    # ── 리스크 평가 ──
    risk_assessment = fields.Html(string="리스크 평가")
    risk_level = fields.Selection(
        [("low", "낮음"), ("medium", "보통"), ("high", "높음"), ("critical", "심각")],
        string="리스크 수준", default="medium", tracking=True,
    )

    # ── 승인 프로세스 ──
    requested_by = fields.Many2one("res.users", string="변경 요청자",
                                    default=lambda self: self.env.user, tracking=True)
    request_date = fields.Date(string="요청일", default=fields.Date.today)
    reviewed_by = fields.Many2one("res.users", string="검토자")
    review_date = fields.Date(string="검토일")
    approved_by = fields.Many2one("res.users", string="승인자")
    approval_date = fields.Date(string="승인일")

    # ── 변경 실행 ──
    planned_date = fields.Date(string="계획 실행일", tracking=True)
    actual_date = fields.Date(string="실제 실행일")
    implemented_by = fields.Many2one("res.users", string="실행자")

    # ── 고객 통보 ──
    customer_notification_required = fields.Boolean(string="고객 통보 필요")
    customer_id = fields.Many2one("res.partner", string="고객")
    customer_approval = fields.Selection(
        [("pending", "대기"), ("approved", "승인"), ("rejected", "거부")],
        string="고객 승인", tracking=True,
    )
    customer_approval_date = fields.Date(string="고객 승인일")

    # ── 검증 ──
    verification_method = fields.Html(string="검증 방법")
    verification_result = fields.Html(string="검증 결과")
    verified_by = fields.Many2one("res.users", string="검증자")
    verification_date = fields.Date(string="검증일")
    effective = fields.Selection(
        [("yes", "유효"), ("no", "무효"), ("partial", "부분 유효")],
        string="유효성", tracking=True,
    )

    # ── FMEA / Control Plan 갱신 ──
    fmea_updated = fields.Boolean(string="FMEA 갱신됨")
    control_plan_updated = fields.Boolean(string="관리계획서 갱신됨")
    work_instruction_updated = fields.Boolean(string="작업지침서 갱신됨")
    ppap_required = fields.Boolean(string="PPAP 재제출 필요")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("requested", "요청됨"),
            ("review", "검토 중"),
            ("approved", "승인됨"),
            ("implementing", "실행 중"),
            ("verification", "검증 중"),
            ("closed", "종료"),
            ("rejected", "반려"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.change.request") or _("New")
        return super().create(vals_list)

    def action_request(self):
        self.write({"state": "requested"})

    def action_review(self):
        self.write({"state": "review", "reviewed_by": self.env.user.id, "review_date": fields.Date.today()})

    def action_approve(self):
        self.write({"state": "approved", "approved_by": self.env.user.id, "approval_date": fields.Date.today()})

    def action_implement(self):
        self.write({"state": "implementing"})

    def action_verify(self):
        self.write({"state": "verification"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_reject(self):
        self.write({"state": "rejected"})
