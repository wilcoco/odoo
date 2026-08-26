"""협력사 포탈 계정 — 관리자가 아이디/비밀번호를 직접 지정.

왜 필요한가:
  기존 action_grant_portal_login 은 계정을 만든 뒤 "비밀번호 설정 초대 메일"에
  의존한다. 그런데 이 서버에는 발신 메일서버가 없고(확인 대기), 있더라도
  협력사 현장 담당자가 메일함을 안 쓰는 경우가 많다. 그러면 계정은 만들어졌는데
  아무도 못 들어오는 상태가 된다.

  그래서 담당자가 전화·카톡으로 알려줄 아이디/비번을 **그 자리에서 직접 지정**
  하는 경로를 둔다. Odoo 기본 change.password.wizard 와 같은 방식(TransientModel
  에 평문을 잠깐 담고 res.users 에 write 하면 해시된다)이지만, 설정>사용자로
  들어가지 않고 협력사 카드에서 바로 끝낼 수 있다.

보안:
  · 남의 비밀번호를 정하는 일이므로 base.group_erp_manager 로 제한한다.
  · 비밀번호는 챗터/로그에 절대 남기지 않는다. 남는 것은 "누가 언제 재설정했다"뿐.
  · 마법사는 transient — 기본 vacuum 이 걷어간다.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)

MIN_PASSWORD_LEN = 8


class SupplierPortalCredentialWizard(models.TransientModel):
    _name = "supplier.portal.credential.wizard"
    _description = "협력사 포탈 계정 아이디/비밀번호 설정"

    partner_id = fields.Many2one(
        "res.partner", string="협력사", required=True, readonly=True)
    user_id = fields.Many2one(
        "res.users", string="기존 포탈 계정", readonly=True,
        help="이미 계정이 있으면 아이디·비밀번호를 이 계정에 적용한다.")
    login = fields.Char(
        string="아이디", required=True,
        help="협력사가 로그인할 때 입력할 ID. 이메일이 아니어도 된다(예: hanwha_resin).")
    # required 는 뷰에서만 건다 — 적용 후 평문을 지워야 하는데
    # 모델 레벨 required 면 NOT NULL 에 걸려 지울 수가 없다.
    new_password = fields.Char(string="비밀번호")
    confirm_password = fields.Char(string="비밀번호 확인")
    portal_url = fields.Char(string="접속 주소", readonly=True)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        partner = self.env["res.partner"].browse(self.env.context.get("active_id"))
        if not partner.exists():
            raise UserError(_("협력사를 먼저 선택하세요."))
        user = self.env["res.users"].sudo().with_context(active_test=False).search(
            [("partner_id", "=", partner.id)], limit=1)
        vals.update({
            "partner_id": partner.id,
            "user_id": user.id or False,
            # 기존 계정이 있으면 그 아이디를 그대로 — 바꾸면 협력사가 못 들어온다.
            "login": user.login or partner.email or "",
            "portal_url": (self.env["ir.config_parameter"].sudo()
                           .get_param("web.base.url") or "") + "/web/login",
        })
        return vals

    def _check_manager(self):
        if not self.env.user.has_group("base.group_erp_manager"):
            raise AccessError(
                _("다른 사용자의 비밀번호를 지정하려면 설정 관리자 권한이 필요합니다."))

    def action_apply(self):
        """계정을 만들거나 찾아서 아이디·비밀번호를 적용한다."""
        self.ensure_one()
        self._check_manager()

        partner = self.partner_id
        if not partner.is_supplier_portal:
            raise UserError(_("'협력사 포탈 사용'이 켜진 협력사에만 계정을 만들 수 있습니다."))

        login = (self.login or "").strip()
        if not login:
            raise ValidationError(_("아이디를 입력하세요."))
        if self.new_password != self.confirm_password:
            raise ValidationError(_("비밀번호와 확인이 일치하지 않습니다."))
        if len(self.new_password or "") < MIN_PASSWORD_LEN:
            raise ValidationError(
                _("비밀번호는 %s자 이상이어야 합니다.") % MIN_PASSWORD_LEN)

        Users = self.env["res.users"].sudo()
        # 아이디 중복은 DB 제약으로도 걸리지만, 그때는 '어느 협력사와 겹쳤는지'를
        # 알 수 없는 메시지가 나온다. 먼저 확인해서 사람이 읽을 수 있게 알린다.
        clash = Users.with_context(active_test=False).search([
            ("login", "=", login), ("partner_id", "!=", partner.id)], limit=1)
        if clash:
            raise ValidationError(
                _("아이디 '%(login)s' 는 이미 '%(who)s' 가 사용 중입니다. 다른 아이디를 쓰세요.")
                % {"login": login, "who": clash.partner_id.display_name or clash.name})

        portal_group = self.env.ref("base.group_portal")
        user = self.user_id.sudo()
        created = False
        if user:
            vals = {"login": login, "password": self.new_password}
            if not user.active:
                vals["active"] = True
            if portal_group not in user.groups_id:
                vals["groups_id"] = [(4, portal_group.id)]
            user.write(vals)
        else:
            user = Users.with_context(no_reset_password=True).create({
                "login": login,
                "name": partner.name,
                "partner_id": partner.id,
                "email": partner.email or False,
                "password": self.new_password,
                "groups_id": [(6, 0, [portal_group.id])],
            })
            created = True

        # 챗터에는 '무엇을 했는지'만 남긴다 — 비밀번호는 절대 기록하지 않는다.
        partner.message_post(body=_(
            "포탈 계정 %(what)s — 아이디 <b>%(login)s</b> (비밀번호는 기록하지 않습니다)."
        ) % {"what": _("생성") if created else _("비밀번호 재설정"), "login": login})
        _logger.info("협력사 포탈 계정 %s: partner=%s login=%s by uid=%s",
                     "created" if created else "password reset",
                     partner.id, login, self.env.uid)

        # 평문은 더 이상 들고 있을 이유가 없다.
        self.sudo().write({"new_password": False, "confirm_password": False,
                           "user_id": user.id})

        return {
            "type": "ir.actions.act_window",
            "res_model": "supplier.portal.credential.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref(
                "supplier_portal_purchase.view_portal_credential_wizard_done").id,
            "target": "new",
            "context": dict(self.env.context, default_partner_id=partner.id),
        }

    def action_close(self):
        return {"type": "ir.actions.act_window_close"}
