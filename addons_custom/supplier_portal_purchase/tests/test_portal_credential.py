"""협력사 포탈 계정 — 관리자 직접 설정.

핵심 주장은 "메일서버 없이도 협력사가 실제로 로그인할 수 있다" 이다.
그래서 비밀번호를 썼다는 것으로 끝내지 않고 자격증명 검증과 실제 HTTP
로그인까지 통과하는지 확인한다.
"""

from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, tagged


PWD = "Cams!2026portal"


@tagged("post_install", "-at_install")
class TestPortalCredential(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({
            "name": "TEST-계정협력사",
            "supplier_rank": 1,
            "is_supplier_portal": True,
        })

    def _wizard(self, partner=None, **vals):
        Wiz = self.env["supplier.portal.credential.wizard"].with_context(
            active_id=(partner or self.partner).id, active_model="res.partner")
        defaults = Wiz.default_get(list(Wiz._fields))
        defaults.update(vals)
        return Wiz.create(defaults)

    def _user_of(self, partner):
        return self.env["res.users"].sudo().with_context(active_test=False).search(
            [("partner_id", "=", partner.id)], limit=1)

    # ── 계정 생성 ───────────────────────────────────────────────
    def test_creates_portal_user_with_given_credentials(self):
        wiz = self._wizard(login="test_cred_supplier",
                           new_password=PWD, confirm_password=PWD)
        wiz.action_apply()

        user = self._user_of(self.partner)
        self.assertTrue(user, "포탈 계정이 만들어져야 한다")
        self.assertEqual(user.login, "test_cred_supplier")
        self.assertTrue(user.has_group("base.group_portal"))
        # 내부 사용자로 만들어지면 Enterprise 시트를 먹는다 — 반드시 포탈이어야 한다
        self.assertFalse(user.has_group("base.group_user"))

    def test_password_actually_authenticates(self):
        """이 테스트가 이 기능의 존재 이유다 — 진짜로 로그인이 되는가."""
        wiz = self._wizard(login="test_cred_auth",
                           new_password=PWD, confirm_password=PWD)
        wiz.action_apply()
        user = self._user_of(self.partner)
        # _login 은 새 커서를 열어 아직 커밋 안 된 테스트 트랜잭션을 못 본다.
        # _check_credentials 는 self.env.user 를 검사하므로 with_user 가 필요하다.
        user = user.with_user(user)
        auth = user._check_credentials(
            {"login": user.login, "password": PWD, "type": "password"},
            {"interactive": False})
        self.assertEqual(auth["uid"], user.id)
        with self.assertRaises(AccessDenied):
            user._check_credentials(
                {"login": user.login, "password": "wrong-password", "type": "password"},
                {"interactive": False})

    def test_partner_form_shows_the_login(self):
        """담당자가 '이 협력사 아이디가 뭐였지'를 설정>사용자 안 가고 알 수 있어야 한다."""
        self.assertFalse(self.partner.portal_login)
        self._wizard(login="test_cred_show",
                     new_password=PWD, confirm_password=PWD).action_apply()
        self.partner.invalidate_recordset(["portal_login"])
        self.assertEqual(self.partner.portal_login, "test_cred_show")

    # ── 재설정 ─────────────────────────────────────────────────
    def test_reset_password_reuses_existing_user(self):
        """두 번째 설정이 계정을 하나 더 만들면 협력사는 어느 걸로 들어갈지 모른다."""
        self._wizard(login="test_cred_reuse",
                     new_password=PWD, confirm_password=PWD).action_apply()
        first = self._user_of(self.partner)

        new_pwd = "Cams!2026changed"
        wiz2 = self._wizard(new_password=new_pwd, confirm_password=new_pwd)
        # 기존 아이디가 기본값으로 채워져 있어야 한다 (실수로 바꾸지 않도록)
        self.assertEqual(wiz2.login, "test_cred_reuse")
        self.assertEqual(wiz2.user_id, first)
        wiz2.action_apply()

        self.assertEqual(len(self.env["res.users"].sudo().with_context(
            active_test=False).search([("partner_id", "=", self.partner.id)])), 1)
        first = first.with_user(first)
        auth = first._check_credentials(
            {"login": "test_cred_reuse", "password": new_pwd, "type": "password"},
            {"interactive": False})
        self.assertEqual(auth["uid"], first.id)
        # 옛 비밀번호는 더 이상 통하면 안 된다
        with self.assertRaises(AccessDenied):
            first._check_credentials(
                {"login": "test_cred_reuse", "password": PWD, "type": "password"},
                {"interactive": False})

    def test_plaintext_is_cleared_after_apply(self):
        """마법사 레코드에 평문이 남아 있으면 DB 에 비번이 굴러다니게 된다."""
        wiz = self._wizard(login="test_cred_clear",
                           new_password=PWD, confirm_password=PWD)
        wiz.action_apply()
        self.assertFalse(wiz.new_password)
        self.assertFalse(wiz.confirm_password)

    def test_password_is_not_written_to_chatter(self):
        wiz = self._wizard(login="test_cred_chatter",
                           new_password=PWD, confirm_password=PWD)
        wiz.action_apply()
        bodies = " ".join(self.partner.message_ids.mapped("body"))
        self.assertIn("test_cred_chatter", bodies)
        self.assertNotIn(PWD, bodies)

    # ── 방어 ───────────────────────────────────────────────────
    def test_mismatched_confirmation_is_rejected(self):
        wiz = self._wizard(login="test_cred_mismatch",
                           new_password=PWD, confirm_password=PWD + "x")
        with self.assertRaises(ValidationError):
            wiz.action_apply()
        self.assertFalse(self._user_of(self.partner))

    def test_short_password_is_rejected(self):
        wiz = self._wizard(login="test_cred_short",
                           new_password="abc", confirm_password="abc")
        with self.assertRaises(ValidationError):
            wiz.action_apply()

    def test_duplicate_login_is_rejected_with_a_readable_message(self):
        """DB 유니크 제약에 맡기면 '어느 협력사와 겹쳤는지'를 알 수 없다."""
        other = self.env["res.partner"].create({
            "name": "TEST-다른협력사", "supplier_rank": 1, "is_supplier_portal": True})
        self._wizard(partner=other, login="test_cred_dup",
                     new_password=PWD, confirm_password=PWD).action_apply()

        wiz = self._wizard(login="test_cred_dup",
                           new_password=PWD, confirm_password=PWD)
        with self.assertRaises(ValidationError) as ctx:
            wiz.action_apply()
        self.assertIn("TEST-다른협력사", str(ctx.exception))

    def test_non_portal_partner_is_rejected(self):
        plain = self.env["res.partner"].create({
            "name": "TEST-포탈미사용", "supplier_rank": 1})
        wiz = self._wizard(partner=plain, login="test_cred_nonportal",
                           new_password=PWD, confirm_password=PWD)
        with self.assertRaises(UserError):
            wiz.action_apply()

    def test_non_admin_cannot_set_someone_elses_password(self):
        """비밀번호 지정은 관리자 권한이다 — 아니면 계정 탈취 경로가 된다."""
        staff = self.env["res.users"].create({
            "login": "test_cred_staff", "name": "TEST-일반직원",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        wiz = self._wizard(login="test_cred_bystaff",
                           new_password=PWD, confirm_password=PWD)
        with self.assertRaises(AccessError) as ctx:
            wiz.with_user(staff).action_apply()
        # ACL 만으로도 막히지만, 그 메시지는 '왜' 막혔는지 알려주지 않는다.
        # 코드 레벨 가드가 실제로 동작하는지를 메시지로 확인한다.
        self.assertIn("설정 관리자 권한", str(ctx.exception))
        self.assertFalse(self._user_of(self.partner))


@tagged("post_install", "-at_install")
class TestPortalCredentialLogin(HttpCase):
    """설정한 계정으로 실제 포탈 화면까지 들어가지는가."""

    def test_supplier_can_reach_portal_after_admin_sets_password(self):
        partner = self.env["res.partner"].create({
            "name": "TEST-로그인협력사", "supplier_rank": 1, "is_supplier_portal": True})
        Wiz = self.env["supplier.portal.credential.wizard"].with_context(
            active_id=partner.id, active_model="res.partner")
        wiz = Wiz.create(dict(Wiz.default_get(list(Wiz._fields)),
                              login="test_cred_e2e",
                              new_password=PWD, confirm_password=PWD))
        wiz.action_apply()
        self.env.flush_all()

        self.authenticate("test_cred_e2e", PWD)
        resp = self.url_open("/supplier/portal")
        self.assertEqual(resp.status_code, 200)
        # 토큰 없이 들어왔는데 거부 화면이면 로그인 경로가 끊긴 것이다
        self.assertNotIn("접근 토큰이 필요합니다", resp.text)
