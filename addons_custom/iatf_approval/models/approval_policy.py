from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfApprovalPolicy(models.Model):
    """전결 규정 — 결재를 쓰는 문서 종류마다 한 줄. 결재 체계(결재선 규칙)는 아래 규정 행으로 입력한다.

    결재 mixin 을 쓰는 모든 문서는 '결재 문서 목록 갱신'으로 빠짐없이 나열된다. 규정 행은
    iatf.approval.template(부서·금액 조건 + 결재선) 이며, 상신 시 가장 구체적인 행이 적용된다."""

    _name = "iatf.approval.policy"
    _description = "전결 규정(문서별 결재 체계)"
    _order = "sequence, name"

    name = fields.Char(string="결재 문서", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one("ir.model", string="문서 모델", required=True, ondelete="cascade", index=True)
    model = fields.Char(related="model_id.model", string="모델명", store=True, readonly=True)
    require_rule = fields.Boolean(
        string="규정 필수",
        help="켜면 이 문서는 전결 규정에 맞는 결재선이 있어야만 상신할 수 있습니다(수동 지정만으로는 상신 불가).")
    lock_lines = fields.Boolean(
        string="결재선 고정",
        help="켜면 상신할 때 결재선을 전결 규정으로 다시 구성합니다. 작성자가 결재자를 바꿀 수 없습니다.")
    note = fields.Text(string="전결 기준", help="예: 500만 원 미만 팀장 전결, 500만 원 이상 대표 결재")
    template_ids = fields.One2many("iatf.approval.template", "policy_id", string="결재 체계")
    template_count = fields.Integer(string="규정 수", compute="_compute_counts")
    request_count = fields.Integer(string="결재 건수", compute="_compute_counts")
    rule_state = fields.Selection([("none", "규정 없음"), ("set", "규정 있음")], string="입력 상태",
                                  compute="_compute_counts")

    _sql_constraints = [("model_unique", "unique(model_id)", "결재 문서마다 전결 규정은 하나입니다.")]

    def _compute_counts(self):
        Request = self.env["iatf.approval.request"].sudo()
        for policy in self:
            policy.template_count = len(policy.template_ids.filtered("active"))
            policy.request_count = Request.search_count([("res_model", "=", policy.model)]) if policy.model else 0
            policy.rule_state = "set" if policy.template_count else "none"

    @api.model
    def _approval_models(self):
        """결재 mixin 을 쓰는 실제 문서 모델(추상·임시 제외)."""
        names = []
        for name in self.env.registry:
            Model = self.env.registry[name]
            if Model._abstract or Model._transient or name == "iatf.approval.request":
                continue
            field = Model._fields.get("approval_request_id")
            if field and field.comodel_name == "iatf.approval.request" and hasattr(Model, "action_submit_approval"):
                names.append(name)
        return sorted(names)

    @api.model
    def _sync_documents(self):
        IrModel = self.env["ir.model"].sudo()
        existing = set(self.sudo().with_context(active_test=False).search([]).mapped("model"))
        created = self.browse()
        for name in self._approval_models():
            if name in existing:
                continue
            ir_model = IrModel._get(name)
            if ir_model:
                created |= self.sudo().create({"name": ir_model.name or name, "model_id": ir_model.id})
        return created

    @api.model
    def action_sync_documents(self):
        if not self.env.user.has_group("base.group_system") and not self.env.su:
            raise UserError(_("전결 규정 문서 목록은 관리자만 갱신할 수 있습니다."))
        created = self._sync_documents()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("결재 문서 목록 갱신"),
                       "message": _("새로 찾은 결재 문서 %d종을 추가했습니다.") % len(created),
                       "type": "success", "next": {"type": "ir.actions.client", "tag": "reload"}},
        }

    @api.model
    def _for_model(self, model_name):
        return self.sudo().search([("model", "=", model_name)], limit=1)

    def action_open_requests(self):
        self.ensure_one()
        return {"type": "ir.actions.act_window", "name": _("결재 이력 — %s") % self.name,
                "res_model": "iatf.approval.request", "view_mode": "list,form",
                "domain": [("res_model", "=", self.model)]}
