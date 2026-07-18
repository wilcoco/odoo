from odoo import api, fields, models, _
from odoo.exceptions import UserError

ACTIVITY_XMLID = "iatf_approval.mail_activity_data_approval"


class IatfApprovalRequest(models.Model):
    _name = "iatf.approval.request"
    _description = "Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    res_model = fields.Char(string="Model", required=True, index=True)
    res_id = fields.Integer(string="Record ID", required=True, index=True)
    requester_id = fields.Many2one(
        "res.users",
        string="Requester",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        "iatf.approval.line",
        "request_id",
        string="Approvers",
        copy=True,
    )
    current_line_id = fields.Many2one(
        "iatf.approval.line",
        compute="_compute_current_line",
        store=True,
    )
    current_approver_id = fields.Many2one(
        "res.users",
        compute="_compute_current_line",
        store=True,
    )
    approved_date = fields.Datetime(string="Approved On", tracking=True)
    rejected_date = fields.Datetime(string="Rejected On", tracking=True)

    @api.depends("line_ids.state", "line_ids.sequence", "line_ids.request_id", "line_ids.user_id")
    def _compute_current_line(self):
        for request in self:
            line = request._get_current_line()
            request.current_line_id = line
            request.current_approver_id = line.user_id if line else False

    def _get_target_record(self):
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return self.env[self.res_model]
        return self.env[self.res_model].browse(self.res_id)

    def _get_ordered_lines(self):
        self.ensure_one()
        return self.line_ids.sorted(key=lambda line: (line.sequence, line.id))

    def _get_current_line(self):
        self.ensure_one()
        lines = self._get_ordered_lines()
        pending = lines.filtered(lambda line: line.state == "pending")
        if pending:
            return pending[0]
        new_lines = lines.filtered(lambda line: line.state == "new")
        return new_lines[:1]

    def _get_next_line(self):
        self.ensure_one()
        for line in self._get_ordered_lines():
            if line.state == "new":
                return line
        return self.env["iatf.approval.line"]

    def _clear_activities(self, record):
        if record and record.exists():
            record.activity_unlink([ACTIVITY_XMLID])

    def _mark_activity_done(self, record, user):
        if record and record.exists():
            record.activity_feedback([ACTIVITY_XMLID], user_id=user.id, feedback=_("Approved"))

    def _schedule_activity(self, record, user):
        if record and record.exists():
            summary = _("Approval required: %s") % (record.display_name or record._name)
            record.activity_schedule(ACTIVITY_XMLID, user_id=user.id, summary=summary)

    def action_submit(self):
        for request in self:
            if not request.line_ids:
                raise UserError(_("Please set at least one approver."))
            request.line_ids.write({"state": "new", "action_date": False, "note": False})
            first_line = request._get_ordered_lines()[:1]
            if not first_line:
                raise UserError(_("Please set at least one approver."))
            first_line.write({"state": "pending"})
            request.write({
                "state": "in_progress",
                "approved_date": False,
                "rejected_date": False,
            })
            record = request._get_target_record()
            request._clear_activities(record)
            request._schedule_activity(record, first_line.user_id)
        return True

    def action_approve(self):
        user = self.env.user
        for request in self:
            request._approve_user(user)
        return True

    def _approve_user(self, user):
        self.ensure_one()
        if self.state != "in_progress":
            raise UserError(_("Approval is not in progress."))
        line = self.current_line_id
        if not line:
            raise UserError(_("No pending approver found."))
        if line.user_id != user:
            raise UserError(_("Only the current approver can approve."))
        line.write({"state": "approved", "action_date": fields.Datetime.now()})
        record = self._get_target_record()
        self._mark_activity_done(record, user)
        next_line = self._get_next_line()
        if next_line:
            next_line.write({"state": "pending"})
            self._schedule_activity(record, next_line.user_id)
        else:
            self.write({"state": "approved", "approved_date": fields.Datetime.now()})
            self._clear_activities(record)
        return True

    def action_reject(self, reason=None):
        user = self.env.user
        for request in self:
            request._reject_user(user, reason=reason)
        return True

    def _reject_user(self, user, reason=None):
        self.ensure_one()
        if self.state != "in_progress":
            raise UserError(_("Approval is not in progress."))
        line = self.current_line_id
        if not line:
            raise UserError(_("No pending approver found."))
        if line.user_id != user:
            raise UserError(_("Only the current approver can reject."))
        line.write({
            "state": "rejected",
            "action_date": fields.Datetime.now(),
            "note": reason,
        })
        record = self._get_target_record()
        self._clear_activities(record)
        self.write({"state": "rejected", "rejected_date": fields.Datetime.now()})
        return True

    def action_reset_draft(self):
        for request in self:
            request.line_ids.write({"state": "new", "action_date": False, "note": False})
            request.write({
                "state": "draft",
                "approved_date": False,
                "rejected_date": False,
            })
            record = request._get_target_record()
            request._clear_activities(record)
        return True


class IatfApprovalLine(models.Model):
    _name = "iatf.approval.line"
    _description = "Approval Line"
    _order = "sequence, id"

    request_id = fields.Many2one(
        "iatf.approval.request",
        string="Approval Request",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    user_id = fields.Many2one("res.users", string="Approver", required=True)
    state = fields.Selection(
        [
            ("new", "Not Started"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="new",
    )
    action_date = fields.Datetime(string="Action Date")
    note = fields.Char(string="Note")
    is_current = fields.Boolean(compute="_compute_is_current")

    @api.depends("request_id.current_line_id")
    def _compute_is_current(self):
        for line in self:
            line.is_current = line.request_id.current_line_id == line


class IatfApprovalMixin(models.AbstractModel):
    _name = "iatf.approval.mixin"
    _description = "Approval Mixin"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    approval_request_id = fields.Many2one(
        "iatf.approval.request",
        string="Approval Request",
        copy=False,
        ondelete="set null",
    )
    approval_state = fields.Selection(
        related="approval_request_id.state",
        string="Approval Status",
        store=True,
        readonly=True,
        tracking=True,
    )
    approval_line_ids = fields.One2many(
        related="approval_request_id.line_ids",
        string="Approvers",
        readonly=False,
    )
    approval_current_approver_id = fields.Many2one(
        related="approval_request_id.current_approver_id",
        string="Current Approver",
        store=True,
        readonly=True,
    )
    approval_is_current_user = fields.Boolean(compute="_compute_approval_is_current_user")

    @api.depends("approval_current_approver_id")
    def _compute_approval_is_current_user(self):
        for record in self:
            record.approval_is_current_user = record.approval_current_approver_id == self.env.user

    def _approval_reset_ignored_fields(self):
        return {
            "approval_request_id",
            "approval_state",
            "approval_current_approver_id",
            "approval_is_current_user",
            "message_ids",
            "message_follower_ids",
            "message_main_attachment_id",
            "activity_ids",
            "activity_state",
            "activity_user_id",
            "activity_type_id",
            "activity_exception_decoration",
            "activity_exception_icon",
            "write_date",
            "write_uid",
            "__last_update",
            "display_name",
        }

    def _approval_should_reset(self, vals):
        return bool(set(vals) - self._approval_reset_ignored_fields())

    def _approval_ensure_request(self):
        for record in self:
            if not record.approval_request_id:
                request = self.env["iatf.approval.request"].create({
                    "res_model": record._name,
                    "res_id": record.id,
                    "requester_id": self.env.user.id,
                })
                record.approval_request_id = request

    @api.model_create_multi
    def create(self, vals_list):
        approval_line_commands_list = []
        for vals in vals_list:
            approval_line_commands_list.append(vals.pop("approval_line_ids", None))

        records = super().create(vals_list)
        records._approval_ensure_request()

        for record, line_commands in zip(records, approval_line_commands_list):
            if line_commands is not None:
                record.approval_request_id.write({"line_ids": line_commands})
        return records

    def write(self, vals):
        line_commands = vals.pop("approval_line_ids", None)
        if line_commands is not None:
            self._approval_ensure_request()
            for record in self:
                record.approval_request_id.write({"line_ids": line_commands})

        res = super().write(vals) if vals else True
        if self._approval_should_reset(vals):
            for record in self:
                if record.approval_state == "approved":
                    record.action_reset_approval()
        return res

    def unlink(self):
        requests = self.mapped("approval_request_id")
        res = super().unlink()
        requests.sudo().unlink()
        return res

    def _approval_amount(self):
        """템플릿 금액 조건용 문서 금액 — 필요한 모델은 오버라이드."""
        self.ensure_one()
        for fname in ("amount_total", "amount", "total_amount"):
            if fname in self._fields:
                try:
                    return float(self[fname] or 0.0)
                except (TypeError, ValueError):
                    continue
        return 0.0

    def _approval_apply_default_template(self):
        """결재선이 비어 있으면 모델/부서/금액 매칭 템플릿으로 자동 구성."""
        Template = self.env["iatf.approval.template"]
        for record in self:
            if record.approval_line_ids:
                continue
            employee = self.env.user.employee_id
            department = employee.department_id if employee else self.env["hr.department"]
            template = Template._find_for(record, record._approval_amount(), department)
            if not template:
                continue
            record.approval_request_id.write({"line_ids": [
                (0, 0, {"sequence": l.sequence, "user_id": l.user_id.id})
                for l in template.line_ids]})
            record.message_post(body="결재선 템플릿 '%s' 자동 적용 (%d단계)"
                                     % (template.name, len(template.line_ids)))

    def action_submit_approval(self):
        for record in self:
            record._approval_ensure_request()
            record._approval_apply_default_template()
            record.approval_request_id.action_submit()
        return True

    def action_approve_approval(self):
        for record in self:
            record.approval_request_id.action_approve()
        return True

    def action_reject_approval(self):
        for record in self:
            record.approval_request_id.action_reject()
        return True

    def action_reset_approval(self):
        for record in self:
            if record.approval_request_id:
                record.approval_request_id.action_reset_draft()
        return True
