import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    """협력사에 포탈 접근 정보 추가"""
    _inherit = "res.partner"

    is_supplier_portal = fields.Boolean(
        string="협력사 포탈 사용",
        default=False,
        help="협력사 포탈을 통해 발주 확인/응답 가능",
    )
    supplier_portal_token_expiry = fields.Date(
        string="포털 토큰 만료일",
        help="이 날짜가 지나면 포털 접근이 거부된다(운영 보안 수칙). "
             "재발급 시 자동으로 오늘+180일로 갱신. 비우면 무기한(권장 안 함).")
    supplier_portal_token = fields.Char(
        string="포탈 접근 토큰",
        copy=False,
        help="협력사 포탈 접근용 보안 토큰",
    )
    portal_notify_email = fields.Char(
        string="발주 알림 이메일",
        help="발주 알림을 받을 이메일 주소 (미입력 시 기본 이메일 사용)",
    )
    portal_language = fields.Selection(
        [
            ("ko_KR", "한국어"),
            ("en_US", "English"),
        ],
        string="포탈 언어",
        default="ko_KR",
    )
    portal_login = fields.Char(
        string="포탈 아이디",
        compute="_compute_portal_login",
        help="이 협력사가 로그인에 쓰는 아이디. "
             "설정 > 사용자로 들어가지 않아도 여기서 확인할 수 있다.")

    def _compute_portal_login(self):
        """협력사에 연결된 포탈 계정의 아이디.

        res.users 는 일반 사용자가 읽을 수 없으므로 sudo 로 조회한다.
        아이디만 노출하며 비밀번호와는 무관하다.
        """
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        for partner in self:
            user = Users.search([("partner_id", "=", partner.id)], limit=1) \
                if partner.id else Users.browse()
            partner.portal_login = user.login or False

    # 통계 필드
    supplier_po_count = fields.Integer(
        string="발주 건수",
        compute="_compute_supplier_stats",
    )
    supplier_pending_count = fields.Integer(
        string="응답 대기 건수",
        compute="_compute_supplier_stats",
    )

    @api.depends("is_supplier_portal")
    def _compute_supplier_stats(self):
        PO = self.env["purchase.order"]
        for partner in self:
            if partner.is_supplier_portal:
                partner.supplier_po_count = PO.search_count([
                    ("partner_id", "=", partner.id),
                    ("auto_generated", "=", True),
                ])
                partner.supplier_pending_count = PO.search_count([
                    ("partner_id", "=", partner.id),
                    ("portal_state", "=", "new"),
                ])
            else:
                partner.supplier_po_count = 0
                partner.supplier_pending_count = 0

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        partners._ensure_portal_token()
        return partners

    def write(self, vals):
        res = super().write(vals)
        if "is_supplier_portal" in vals:
            self._ensure_portal_token()
        return res

    def _ensure_portal_token(self):
        """협력사 포털 사용 파트너는 항상 강한 랜덤 토큰을 갖도록 보장.
        (토큰 미생성 상태로 포털이 열리는 프로비저닝 갭 방지)"""
        for partner in self:
            if partner.is_supplier_portal and not partner.supplier_portal_token:
                partner.supplier_portal_token = secrets.token_urlsafe(32)
                partner.supplier_portal_token_expiry = fields.Date.add(
                    fields.Date.context_today(partner), days=180)

    def action_generate_portal_token(self):
        """포탈 접근 토큰 (재)생성"""
        for partner in self:
            partner.supplier_portal_token = secrets.token_urlsafe(32)
        self.supplier_portal_token_expiry = fields.Date.add(fields.Date.context_today(self), days=180)
        return True

    def action_grant_portal_login(self):
        """협력사에 아이디/비번 포탈 로그인 부여 (토큰과 공존).

        이메일을 로그인 ID 로 포탈 유저를 만들고(이미 있으면 포탈 그룹 보장),
        비밀번호 설정 초대 메일을 보낸다. 메일서버가 없으면 계정만 만들고
        설정>사용자에서 비번을 직접 지정하도록 안내(계정은 유지).
        """
        self.ensure_one()
        if not self.email:
            raise UserError(_("포탈 로그인 부여에는 이메일(로그인 ID)이 필요합니다."))
        if not self.is_supplier_portal:
            raise UserError(_("협력사 포탈 사용이 켜진 파트너에만 부여할 수 있습니다."))
        Users = self.env["res.users"].sudo()
        portal_group = self.env.ref("base.group_portal")
        user = Users.with_context(active_test=False).search(
            [("partner_id", "=", self.id)], limit=1)
        if user:
            vals = {"groups_id": [(4, portal_group.id)]}
            if not user.active:
                vals["active"] = True
            user.write(vals)
        else:
            user = Users.with_context(no_reset_password=True).create({
                "login": self.email, "name": self.name, "partner_id": self.id,
                "email": self.email, "groups_id": [(6, 0, [portal_group.id])],
            })
        try:
            user.action_reset_password()
            msg = _("포탈 로그인 부여 완료 — 비밀번호 설정 초대 메일을 발송했습니다.")
        except Exception as e:  # 메일서버 미구성 등 — 계정은 유지
            _logger.warning("포탈 초대 메일 실패(%s): %s", self.email, e)
            msg = _("포탈 로그인 계정을 만들었습니다. 메일 발송이 안 돼 "
                    "설정 > 사용자에서 비밀번호를 직접 지정해 주세요.")
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("협력사 포탈 로그인"), "message": msg,
                       "type": "success", "sticky": False},
        }

    def action_view_supplier_pos(self):
        """협력사의 발주 목록 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"{self.name} 발주 목록",
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [
                ("partner_id", "=", self.id),
                ("auto_generated", "=", True),
            ],
            "context": {"default_partner_id": self.id},
        }
