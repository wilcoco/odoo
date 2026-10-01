from odoo import api, fields, models, _
from odoo.exceptions import UserError


class OpsTask(models.Model):
    """업무 건 — '이번 기간에 해야 할 그 업무'. todo → 완료보고 → 승인.

    지연(is_overdue)은 기한 경과+미완료. 승인 이력은 채터로 추적."""

    _name = "ops.task"
    _description = "운영 업무 건"
    _order = "due_date, id"
    _inherit = ["mail.thread"]
    _rec_name = "display_label"

    task_def_id = fields.Many2one("ops.task.def", string="업무", required=True,
                                  ondelete="cascade", index=True)
    role_id = fields.Many2one(related="task_def_id.role_id", string="담당 역할",
                              store=True, index=True)
    periodicity = fields.Selection(related="task_def_id.periodicity", store=True)
    period_key = fields.Char(string="기간", index=True)
    display_label = fields.Char(compute="_compute_display_label", store=True)

    scheduled_date = fields.Date(string="예정일", required=True)
    due_date = fields.Date(string="기한", index=True)

    state = fields.Selection([
        ("todo", "해야 함"),
        ("done", "완료 보고"),
        ("approved", "승인됨"),
        ("cancel", "건너뜀"),
    ], default="todo", string="상태", tracking=True, index=True)

    done_uid = fields.Many2one("res.users", string="완료자", readonly=True)
    done_date = fields.Datetime(string="완료 시각", readonly=True)
    done_note = fields.Text(string="수행 메모/결과")
    approve_uid = fields.Many2one("res.users", string="승인자", readonly=True)
    approve_date = fields.Datetime(string="승인 시각", readonly=True)

    is_overdue = fields.Boolean(compute="_compute_overdue", search="_search_overdue",
                                string="지연")
    manual_html = fields.Html(related="task_def_id.manual_html", string="업무 매뉴얼")
    menu_path = fields.Char(related="task_def_id.menu_path")
    requires_approval = fields.Boolean(related="task_def_id.requires_approval")

    _sql_constraints = [
        ("def_period_uniq", "unique(task_def_id, period_key)",
         "같은 업무의 같은 기간 건이 이미 존재합니다(중복 생성 방지)."),
    ]

    @api.depends("task_def_id.name", "period_key")
    def _compute_display_label(self):
        for t in self:
            t.display_label = "%s [%s]" % (t.task_def_id.name or "?", t.period_key or "")

    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for t in self:
            t.is_overdue = bool(t.due_date and t.due_date < today
                                and t.state == "todo")

    def _search_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        dom = [("state", "=", "todo"), ("due_date", "<", today)]
        truthy = (operator == "=" and value) or (operator == "!=" and not value)
        return dom if truthy else ["!"] + dom

    # ── 상태 전이 ──
    def action_mark_done(self):
        for t in self:
            if not t._can_complete(self.env.user):
                raise UserError(_("완료 보고 권한이 없습니다 — 담당 역할 또는 운영관리자만 처리할 수 있습니다."))
            if t.state != "todo":
                raise UserError(_("'해야 함' 상태의 업무만 완료 보고할 수 있습니다."))
            vals = {"done_uid": self.env.uid, "done_date": fields.Datetime.now()}
            # 승인 불요 업무는 완료 즉시 승인됨 처리
            vals["state"] = "done" if t.requires_approval else "approved"
            t.write(vals)
            t.message_post(body=_("완료 보고: %s") % self.env.user.name)
        return True

    def _can_complete(self, user):
        self.ensure_one()
        if self.env.su or user.has_group("cams_ops_process.group_ops_manager"):
            return True
        department_ids = user.employee_ids.mapped("department_id")
        return bool(user in self.role_id.user_ids or self.role_id.department_ids & department_ids)

    def action_approve(self):
        for t in self:
            if t.state != "done":
                raise UserError(_("완료 보고된 업무만 승인할 수 있습니다."))
            if not t._can_approve(self.env.user):
                raise UserError(_("승인 권한이 없습니다 — 승인 역할(%s) 또는 운영관리자만 승인할 수 있습니다.")
                                % (t.task_def_id.approver_role_id.name or _("운영관리자")))
            t.write({"state": "approved", "approve_uid": self.env.uid,
                     "approve_date": fields.Datetime.now()})
            t.message_post(body=_("승인: %s") % self.env.user.name)
        return True

    def _can_approve(self, user):
        self.ensure_one()
        if self.env.su:
            return True
        if user.has_group("cams_ops_process.group_ops_manager"):
            return True
        ar = self.task_def_id.approver_role_id
        if not ar:
            return False
        department_ids = user.employee_ids.mapped("department_id")
        return bool(user in ar.user_ids or ar.department_ids & department_ids)

    def action_reset_todo(self):
        for t in self:
            t.write({"state": "todo", "done_uid": False, "done_date": False,
                     "approve_uid": False, "approve_date": False})
            t.message_post(body=_("재작업으로 되돌림: %s") % self.env.user.name)
        return True

    def action_skip(self):
        for t in self:
            if t.state == "approved":
                raise UserError(_("승인된 업무는 건너뛸 수 없습니다."))
            t.write({"state": "cancel"})
            t.message_post(body=_("건너뜀 처리: %s") % self.env.user.name)
        return True

    def action_open_target(self):
        """업무 대상 화면 열기(정의에 액션이 설정된 경우)."""
        self.ensure_one()
        act = self.task_def_id.menu_action_id
        if not act:
            raise UserError(_("이 업무에는 바로가기 화면이 설정되어 있지 않습니다.\n메뉴 경로: %s")
                            % (self.menu_path or "-"))
        return act.sudo().read()[0]
