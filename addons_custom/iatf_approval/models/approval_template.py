import json

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.osv import expression


class IatfApprovalTemplate(models.Model):
    """기본 결재선 템플릿 — 모델/부서/금액 조건으로 매칭해 상신 시 결재선을 자동 구성.
    운영에서 매 문서마다 결재선을 수동 지정하는 부담 제거 (1번 세션 E2E 제안 4)."""
    _name = "iatf.approval.template"
    _description = "결재선 템플릿"
    _order = "sequence, id"

    name = fields.Char(string="템플릿명", required=True)
    active = fields.Boolean(default=True)
    # Existing unscoped rules remain unchanged until an explicit data review.
    company_id = fields.Many2one('res.company', string='적용 회사', index=True)
    match_domain = fields.Text(string='추가 문서 조건 (JSON)', default='[]',
        help='예: [["audit_type", "=", "sq"]]. 빈 배열이면 문서 종류를 추가 제한하지 않습니다.')
    configuration_note = fields.Text(string='결재선 사전 점검', compute='_compute_configuration_note')
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
    line_summary = fields.Char(string="결재 순서", compute="_compute_line_summary")
    policy_id = fields.Many2one("iatf.approval.policy", string="전결 규정", ondelete="cascade", index=True,
                                help="전결 규정(문서별 결재 체계) 화면에서 입력한 규정 행. 문서 모델은 규정의 문서로 고정됩니다.")

    @api.depends("line_ids.sequence", "line_ids.approver_mode", "line_ids.user_id")
    def _compute_line_summary(self):
        for template in self:
            template.line_summary = " → ".join(
                "%d. %s" % (i, line._approver_label()) for i, line in enumerate(template.line_ids.sorted(lambda l: (l.sequence, l.id)), 1))

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        Policy = self.env["iatf.approval.policy"]
        for vals in vals_list:
            vals.setdefault('company_id', self.env.company.id)
            if vals.get("policy_id"):
                vals["model_id"] = Policy.browse(vals["policy_id"]).model_id.id
            elif vals.get("model_id"):
                policy = Policy.sudo().search([("model_id", "=", vals["model_id"])], limit=1)
                if policy:
                    vals["policy_id"] = policy.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("policy_id"):
            vals = dict(vals, model_id=self.env["iatf.approval.policy"].browse(vals["policy_id"]).model_id.id)
        elif "model_id" in vals:
            policy = self.env["iatf.approval.policy"].sudo().search([("model_id", "=", vals["model_id"])], limit=1)                 if vals["model_id"] else self.env["iatf.approval.policy"]
            vals = dict(vals, policy_id=policy.id or False)
        return super().write(vals)

    def _parsed_match_domain(self):
        self.ensure_one()
        try:
            domain = json.loads(self.match_domain or '[]')
            if not isinstance(domain, list):
                raise ValueError('Expected list')
            expression.normalize_domain(domain)
            if domain and not self.model_id:
                raise ValueError('Model required')
            for leaf in domain:
                if isinstance(leaf, str) and leaf in ('&', '|', '!'):
                    continue
                if not isinstance(leaf, list) or len(leaf) != 3:
                    raise ValueError('Invalid leaf')
                if leaf[1] not in expression.TERM_OPERATORS:
                    raise ValueError('Invalid operator')
                if leaf[0] in (0, 1):
                    continue
                model = self.env[self.model_id.model]
                for name in leaf[0].split('.'):
                    field = model._fields.get(name)
                    if not field:
                        raise ValueError('Unknown field')
                    model = self.env[field.comodel_name] if field.relational else model
            return domain
        except (ValueError, TypeError, KeyError, AttributeError, AssertionError) as error:
            raise ValidationError(_('추가 문서 조건은 적용 모델의 실제 필드를 사용하는 JSON 도메인이어야 합니다.')) from error

    @api.constrains('match_domain', 'model_id', 'company_id', 'department_id')
    def _check_template_scope(self):
        for template in self:
            template._parsed_match_domain()
            if template.company_id and template.department_id.company_id != template.company_id and template.department_id:
                raise ValidationError(_('결재선 적용 회사와 상신자 부서 회사가 다릅니다.'))

    @api.depends('line_ids.user_id', 'line_ids.approver_mode', 'model_id', 'company_id', 'department_id')
    def _compute_configuration_note(self):
        for template in self:
            notes = []
            if not template.company_id:
                notes.append(_('회사 미지정: 기존 공통 규칙의 적용 범위를 확인하십시오.'))
            if not template.department_id:
                notes.append(_('부서 미지정: 모든 부서에 적용될 수 있습니다.'))
            if not template.line_ids:
                notes.append(_('결재 단계가 없습니다.'))
            for line in template.line_ids:
                if line.approver_mode != 'user':
                    notes.append(_('부서장 단계는 상신 문서와 사용자 기준으로 다시 점검합니다.'))
                    continue
                user = line.user_id
                if not user.active or user.share:
                    notes.append(_('%s: 활성 내부 사용자가 아닙니다.') % user.display_name)
                if template.company_id and template.company_id not in user.company_ids:
                    notes.append(_('%s: 적용 회사 권한이 없습니다.') % user.display_name)
                if template.model_id and not self.env[template.model_id.model].with_user(user).check_access_rights('write', raise_exception=False):
                    notes.append(_('%s: 대상 문서 쓰기 권한이 없습니다. 해당 업무 승인 역할을 지정하십시오.') % user.display_name)
            template.configuration_note = '\n'.join(notes) or _('기본 권한 점검 통과. 실제 문서·회사·자기결재·순서는 상신 시 다시 검증합니다.')

    @api.model
    def _find_for(self, record, amount, department):
        """가장 구체적인 템플릿 1개: 모델일치 > 부서일치 > 금액하한 큰 순 > sequence."""
        company = (record.company_id if 'company_id' in record._fields else False) or self.env.company
        domain = [
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
            "|", ("model_id", "=", False), ("model_id.model", "=", record._name),
            "|", ("department_id", "=", False),
            ("department_id", "=", department.id if department else False),
            # 2026-09-27 T7-b: 금액 하한 0 은 도움말대로 '금액 무관'이다. 환입·가감처럼 문서 금액이
            # 음수인 경우 `0 <= 음수` 가 거짓이 되어 하한 0 템플릿까지 빠지던 결함을 고친다.
            # 양수 하한은 그대로 문서 금액과 비교한다(음수 금액에 크기 기준을 적용할지는 정책 미정).
            "|", ("min_amount", "=", 0.0), ("min_amount", "<=", amount),
        ]
        candidates = self.search(domain)
        candidates = candidates.filtered(lambda t: t.line_ids and record.filtered_domain(t._parsed_match_domain()))
        if not candidates:
            return self.browse()
        return candidates.sorted(
            key=lambda t: (bool(t.model_id), bool(t.company_id), bool(t.department_id), bool(t._parsed_match_domain()), t.min_amount, -t.sequence),
            reverse=True)[0]


class IatfApprovalTemplateLine(models.Model):
    _name = "iatf.approval.template.line"
    _description = "결재선 템플릿 라인"
    _order = "sequence, id"

    template_id = fields.Many2one("iatf.approval.template", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    approver_mode = fields.Selection([
        ("user", "지정 사용자"),
        ("manager", "작성자의 부서장(본인이면 상위 부서장)"),
    ], string="결재자 방식", default="user", required=True,
        help="'작성자의 부서장'은 상신 시점에 상신자 소속 부서의 부서장으로 결정됩니다. "
             "부서장 미지정 등으로 결정할 수 없으면 템플릿을 적용하지 않고 수동 지정을 요구합니다.")
    user_id = fields.Many2one("res.users", string="결재자")
    # 전결 규정표(한 화면 목록·엑셀 내보내기)용
    rule_policy_id = fields.Many2one(related="template_id.policy_id", string="결재 문서", store=True, readonly=True)
    rule_name = fields.Char(related="template_id.name", string="규정", readonly=True)
    rule_department_id = fields.Many2one(related="template_id.department_id", string="상신자 부서", readonly=True)
    rule_min_amount = fields.Float(related="template_id.min_amount", string="금액 하한", readonly=True)
    rule_active = fields.Boolean(related="template_id.active", string="사용", readonly=True)
    approver_label = fields.Char(string="결재자", compute="_compute_approver_label")

    def _approver_label(self):
        self.ensure_one()
        mode = dict(self._fields["approver_mode"]._description_selection(self.env)).get(self.approver_mode, self.approver_mode)
        return "%s(%s)" % (mode, self.user_id.name) if self.approver_mode == "user" and self.user_id else mode

    @api.depends("approver_mode", "user_id")
    def _compute_approver_label(self):
        for line in self:
            line.approver_label = line._approver_label()

    _sql_constraints = [
        ("user_required_when_fixed",
         "CHECK (approver_mode != 'user' OR user_id IS NOT NULL)",
         "'지정 사용자' 방식 라인에는 결재자를 지정해야 합니다."),
    ]

    def _resolve_user(self, requester):
        """상신자 기준으로 이 라인의 실제 결재자를 결정. 결정 불가 시 빈 recordset."""
        self.ensure_one()
        if self.approver_mode == "manager":
            # 작성자 본인이 부서장이면 상위 부서의 부서장으로 올라간다(자기결재 금지).
            emp = requester.employee_id
            department = emp.department_id if emp else self.env["hr.department"]
            seen = self.env["hr.department"]
            while department and department not in seen:
                seen |= department
                manager_user = department.manager_id.user_id
                if manager_user and manager_user != requester:
                    return manager_user
                department = department.parent_id
            return self.env["res.users"]
        return self.user_id
