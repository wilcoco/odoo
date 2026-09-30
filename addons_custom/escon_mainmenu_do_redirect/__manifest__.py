# -*- coding: utf-8 -*-
{
    "name": "ESCON 메인 메뉴 - 홈 교체(리다이렉트)",
    "summary": "설치하면 로그인 첫 화면과 홈 버튼(⊞)이 ESCON 메인 메뉴로 교체된다",
    "description": """
ESCON 메인 메뉴 홈 교체
=======================
escon_mainmenu 는 '홈' 앱만 제공하고, 실제 홈 교체는 이 모듈이 담당한다.

- 설치 시:
  - Enterprise: 홈 메뉴("menu" 클라이언트 액션, 앱 그리드)를 ESCON 메인 메뉴로 교체
    (원본은 "Odoo 기본 홈 보기"로 계속 접근 가능)
  - Community: 네비바 왼쪽 앱 드롭다운을 홈 이동 버튼으로 교체
  - 내부 사용자의 홈 액션(action_id)을 ESCON 메인 메뉴로 지정
    (이미 지정된 사용자는 존중)
- 제거 시: 홈 액션 지정을 되돌리고 기본 Odoo 홈 동작으로 복귀
""",
    "version": "18.0.1.0.0",
    "category": "Productivity",
    "license": "LGPL-3",
    "author": "ESCON",
    "depends": ["escon_mainmenu"],
    "assets": {
        "web.assets_backend": [
            "escon_mainmenu_do_redirect/static/src/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
    "installable": True,
    "application": False,
}
