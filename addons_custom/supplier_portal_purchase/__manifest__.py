{
    "name": "외주 자동발주 및 협력사 포탈",
    "version": "18.0.1.0.0",
    "summary": "생산계획 기반 외주 자동발주 + 협력사 포탈 (응답/승인 워크플로우)",
    "description": """
외주 자동발주 및 협력사 포탈 시스템
====================================

주요 기능:
- 생산계획(injection_planning) 확정 시 외주 부품 자동 발주
- 협력사 포탈: 발주 확인, 납기/수량 응답
- 구매담당자: 응답 검토, 승인/반려
- 생산 영향도 자동 분석
- Odoo 표준 입고/재고/회계 연동
    """,
    "category": "Inventory/Purchase",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": [
        "injection_planning",
        "purchase",
        "stock",
        "portal",
        "website",
        "mail",
    ],
    "data": [
        # Security
        "security/security.xml",
        "security/ir.model.access.csv",
        # Data
        "data/sequence.xml",
        "data/cron.xml",
        # Views - Models
        "views/product_outsource_views.xml",
        "views/partner_portal_views.xml",
        "views/purchase_order_views.xml",
        "views/purchase_response_views.xml",
        "views/notification_views.xml",
        "views/planning_config_views.xml",
        "views/outsource_planning_views.xml",
        "views/menu.xml",
        # Portal Templates
        "views/portal_templates.xml",
        # Wizards
        "wizards/purchase_reject_wizard_views.xml",
        "wizards/generate_outsource_demo_wizard_views.xml",
    ],
    "demo": [
        "data/demo/res_partner_demo.xml",
        "data/demo/res_users_demo.xml",
        "data/demo/product_demo.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "supplier_portal_purchase/static/src/css/portal.css",
            "supplier_portal_purchase/static/src/js/portal.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
