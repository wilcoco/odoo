from odoo import Command, api, fields, models, _
from odoo.exceptions import AccessError, UserError


class AccountKrManualFlagWizard(models.TransientModel):
    """매출·매입 목록에서 선택한 전표의 수기 표시를 확인 절차를 거쳐 변경한다."""

    _name = "account.kr.manual.flag.wizard"
    _description = "수기 표시 변경"

    move_ids = fields.Many2many(
        "account.move", string="대상 전표", required=True,
        domain="[('move_type', '!=', 'entry')]")
    action = fields.Selection(
        [("clear", "수기 표시 해제"), ("set", "수기 표시 설정")],
        string="처리", default="clear", required=True)
    move_count = fields.Integer(string="선택 건수", compute="_compute_counts")
    change_count = fields.Integer(string="변경될 건수", compute="_compute_counts")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if "move_ids" in fields_list and self.env.context.get("active_model") == "account.move":
            values["move_ids"] = [Command.set(self.env.context.get("active_ids", []))]
        return values

    @api.depends("move_ids", "action")
    def _compute_counts(self):
        for wizard in self:
            target = wizard.action == "set"
            wizard.move_count = len(wizard.move_ids)
            wizard.change_count = len(
                wizard.move_ids.filtered(lambda m: bool(m.is_manually_modified) != target)
            )

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group("account.group_account_manager"):
            raise AccessError(_("회계 관리자만 수기 표시를 변경할 수 있습니다."))
        if not self.move_ids:
            raise UserError(_("대상 전표가 없습니다."))
        target = self.action == "set"
        moves = self.move_ids.filtered(lambda m: bool(m.is_manually_modified) != target)
        # 사람이 확인 버튼을 눌러 바꾸는 것이지만, 이 변경 자체가 다시 '수기'로 찍히면 안 된다.
        moves.with_context(skip_is_manually_modified=True).write(
            {"is_manually_modified": target}
        )
        for move in moves:
            move.message_post(body=_(
                "수기 표시 %(what)s (선택 변경, %(user)s)",
                what=_("설정") if target else _("해제"), user=self.env.user.name))
        return {"type": "ir.actions.client", "tag": "reload"}
