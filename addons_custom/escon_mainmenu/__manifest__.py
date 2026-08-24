# -*- coding: utf-8 -*-
{
    "name": "ESCON 메인 메뉴",
    "summary": "로그인 첫 화면 — 업무 카테고리별 타일 홈 (입고/생산/재고/출고·판매/회계/인사/전체 메뉴)",
    "description": """
ESCON 메인 메뉴 (홈 대시보드)
=============================
OWL 클라이언트 액션으로 구현한 홈 화면.
7개 업무 카테고리 타일에서 Odoo 표준 메뉴와 자사 모듈의 핵심 화면으로 바로 이동한다.

- 메뉴 목록은 웹클라이언트 menu 서비스(load_web_menus)에서 xmlid로 해석하므로
  미설치 모듈·접근권한 없는 메뉴는 자동으로 숨겨진다 (별도 서버 로직 없음).
- 설치 시 내부 사용자의 홈 액션(action_id)을 이 화면으로 지정한다
  (이미 홈 액션이 지정된 사용자는 건드리지 않음).
""",
    "version": "18.0.1.0.0",
    "category": "Productivity",
    "license": "LGPL-3",
    "author": "ESCON",
    "depends": ["web"],
    "data": [
        "security/ir.model.access.csv",
        "security/security.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "escon_mainmenu/static/src/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": True,
}
