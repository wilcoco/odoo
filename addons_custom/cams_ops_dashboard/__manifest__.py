{
    "name": "회사 운영 센터 대시보드",
    "version": "18.0.3.0.0",
    "summary": "사용자·부서·역할별 오늘의 업무와 승인 대기 현황, 회사 운영 흐름(4단 캐스케이드)",
    "category": "Productivity",
    "license": "LGPL-3",
    "author": "CAMS",
    "depends": ["web", "cams_ops_process"],
    "data": [
        "security/ir.model.access.csv",
        "views/ops_dashboard_views.xml",
        "views/factory_flow_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cams_ops_dashboard/static/src/dashboard/ops_dashboard.js",
            "cams_ops_dashboard/static/src/dashboard/ops_dashboard.xml",
            "cams_ops_dashboard/static/src/dashboard/ops_dashboard.scss",
            "cams_ops_dashboard/static/src/factory_flow/factory_flow.js",
            "cams_ops_dashboard/static/src/factory_flow/factory_flow.xml",
            "cams_ops_dashboard/static/src/factory_flow/factory_flow.scss",
        ],
        "web.assets_tests": [
            "cams_ops_dashboard/static/tests/tours/factory_flow_tour.js",
        ],
    },
    "application": False,
    "auto_install": True,
    "installable": True,
}
