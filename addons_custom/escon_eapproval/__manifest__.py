{
    "name": "에스콘 전자결재",
    "version": "18.0.3.3.0",
    "summary": "통합 전자결재 앱 — 결재 대시보드(OWL)·부서/직급 기반 결재선·품의서/휴가 연동 뼈대",
    "description": """
에스콘 전자결재
===============
- iatf_approval 의 도메인 중립 결재 엔진(iatf.approval.mixin)을 회사 공용 전자결재로 승격
- 계정(직원)별 부서/직급 설정 + 결재선 템플릿의 부서/직급 기반 결재자 자동 결정
- OWL 대시보드: 내 결재 대기 · 내 상신 현황 · 품의서 현황 · 휴가 현황 (사출 현장 대시보드 디자인 차용)
- 휴가 신청/내 휴가/휴가 승인 메뉴 (Odoo hr_holidays 연동)
- 품의서(pumui_approval) 등 결재 문서 모듈이 이 앱 메뉴 아래로 연결됨
""",
    "category": "Human Resources/Approvals",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "web", "hr", "hr_holidays", "iatf_approval",
                "approvals", "approvals_purchase"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/leave_type_data.xml",
        "data/annual_leave_cron.xml",
        "data/approval_category_data.xml",
        "data/approval_setup.xml",
        "views/job_grade_views.xml",
        "views/approval_request_views.xml",
        "views/approval_template_views.xml",
        "views/menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "escon_eapproval/static/src/dashboard/eapproval_dashboard.js",
            "escon_eapproval/static/src/dashboard/eapproval_dashboard.xml",
            "escon_eapproval/static/src/dashboard/eapproval_dashboard.scss",
            "escon_eapproval/static/src/dashboard/eapproval_compose.js",
            "escon_eapproval/static/src/dashboard/eapproval_compose.xml",
        ],
    },
    "installable": True,
    "application": True,
}
