from odoo import api, fields, models


class IatfApprovalTemplate(models.Model):
    """기본 결재선 템플릿 — 모델/부서/금액 조건으로 매칭해 상신 시 결재선을 자동 구성.
    운영에서 매 문서마다 결재선을 수동 지정하는 부담 제거 (1번 세션 E2E 제안 4)."""
    _name = "iatf.approval.template"
    _description = "결재선 템플릿"
    _order = "sequence, id"

    name = fields.Char(string="템플릿명", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    model_id = fields.Many2one(
        "ir.model", string="적용 모델", ondelete="cascade",
        help="비우면 결재 mixin 을 쓰는 모든 모델에 적용")
    department_id = fields.Many2one(
        "hr.department", string="상신자 부서",
        help="비우면 부서 무관. 상신자(요청자)의 소속 부서와 매칭")
    min_amount = fields.Float(
        string="금액 하한", default=0.0,
        help="문서 금액이 이 값 이상일 때 적용 (0 = 금액 무관). "
             "문서 금액은 amount_total/amount/total_amount 필드에서 자동 인식")
    line_ids = fields.One2many("iatf.approval.template.line", "template_id", string="결재선")

    @api.model
    def _find_for(self, record, amount, department):
        """가장 구체적인 템플릿 1개: 모델일치 > 부서일치 > 금액하한 큰 순 > sequence."""
        domain = [
            "|", ("model_id", "=", False), ("model_id.model", "=", record._name),
            "|", ("department_id", "=", False),
            ("department_id", "=", department.id if department else False),
            ("min_amount", "<=", amount),
        ]
        candidates = self.search(domain)
        candidates = candidates.filtered(lambda t: t.line_ids)
        if not candidates:
            return self.browse()
        return candidates.sorted(
            key=lambda t: (bool(t.model_id), bool(t.department_id), t.min_amount, -t.sequence),
            reverse=True)[0]


class IatfApprovalTemplateLine(models.Model):
    _name = "iatf.approval.template.line"
    _description = "결재선 템플릿 라인"
    _order = "sequence, id"

    template_id = fields.Many2one("iatf.approval.template", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    approver_mode = fields.Selection([
        ("user", "지정 사용자"),
        ("manager", "작성자의 부서장"),
    ], string="결재자 방식", default="user", required=True,
        help="'작성자의 부서장'은 상신 시점에 상신자 소속 부서의 부서장으로 결정됩니다. "
             "부서장 미지정 등으로 결정할 수 없으면 템플릿을 적용하지 않고 수동 지정을 요구합니다.")
    user_id = fields.Many2one("res.users", string="결재자")

    _sql_constraints = [
        ("user_required_when_fixed",
         "CHECK (approver_mode != 'user' OR user_id IS NOT NULL)",
         "'지정 사용자' 방식 라인에는 결재자를 지정해야 합니다."),
    ]

    def _resolve_user(self, requester):
        """상신자 기준으로 이 라인의 실제 결재자를 결정. 결정 불가 시 빈 recordset."""
        self.ensure_one()
        if self.approver_mode == "manager":
            emp = requester.employee_id
            mgr = emp.department_id.manager_id if emp and emp.department_id else False
            return mgr.user_id if mgr and mgr.user_id else self.env["res.users"]
        return self.user_id
