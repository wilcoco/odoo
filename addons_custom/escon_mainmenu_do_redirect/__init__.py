# -*- coding: utf-8 -*-


def post_init_hook(env):
    """내부 사용자의 홈 액션을 ESCON 메인 메뉴로 지정한다.

    이미 홈 액션을 따로 지정해 둔 사용자는 존중하고 건드리지 않는다.
    """
    action = env.ref("escon_mainmenu.action_escon_mainmenu", raise_if_not_found=False)
    if not action:
        return
    users = env["res.users"].with_context(active_test=False).search(
        [("share", "=", False), ("action_id", "=", False)]
    )
    users.write({"action_id": action.id})


def uninstall_hook(env):
    """홈 액션 지정을 되돌려 기본 Odoo 홈 동작으로 복귀시킨다."""
    action = env.ref("escon_mainmenu.action_escon_mainmenu", raise_if_not_found=False)
    if not action:
        return
    users = env["res.users"].with_context(active_test=False).search(
        [("action_id", "=", action.id)]
    )
    users.write({"action_id": False})
