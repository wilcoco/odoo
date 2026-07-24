{
    "name": "품의서 (결재·청구서 연계)",
    "version": "18.0.1.0.0",
    "summary": "품의서 작성→다단계 결재(승인/반려)→청구서 생성·잔액 관리. 승인 전 전기 차단. (회계 사용 리포트 #6·#7 대응)",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "DevSanx",
    # 결재선은 검증된 iatf.approval.mixin 재사용 (도메인 중립 결재 엔진)
    "depends": ["account", "mail", "product", "project", "iatf_approval"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/pumui_views.xml",
        "views/account_move_views.xml",
        "wizard/make_invoice_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
}
