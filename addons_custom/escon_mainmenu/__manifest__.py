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
- 이 모듈은 '홈' 앱만 추가한다. 로그인 첫 화면·홈 버튼(⊞) 교체는
  escon_mainmenu_do_redirect 모듈이 담당한다 (미설치 시 기본 Odoo 홈 유지).
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
    "installable": True,
    "application": True,
}
