"""[BOM 관리체계 점검 A4] 샘플 데이터 생성은 시스템 관리자만 — 관리 BOM 을 지우는 도구."""
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestDemoGeneratorAdminOnly(TransactionCase):

    def _planning_manager(self):
        group = self.env.ref("injection_planning.group_planning_manager")
        return self.env["res.users"].create({
            "name": "계획 관리자(비시스템)", "login": "bom_a4_planning_manager",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id, group.id])],
        })

    def test_planning_manager_cannot_run_demo_generator(self):
        """계획 관리자 권한만으로는 샘플 데이터 생성을 실행할 수 없다(RPC 포함)."""
        user = self._planning_manager()
        wizard = self.env["injection.generate.demo.wizard"].with_user(user).create({})
        with self.assertRaises(AccessError):
            wizard.action_generate()

    def test_menu_and_action_restricted_to_system_group(self):
        """메뉴와 액션 모두 시스템 관리자 그룹에만 보인다."""
        system = self.env.ref("base.group_system")
        menu = self.env.ref("injection_planning.menu_generate_demo")
        action = self.env.ref("injection_planning.action_generate_demo")
        self.assertIn(system, menu.groups_id)
        self.assertIn(system, action.groups_id)
