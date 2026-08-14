{
    "name": "회계 한국화 가드·점검 (K-Guard)",
    "version": "18.0.1.0.0",
    "summary": "결제대기계정 가드·사업자번호 중복 경고·청구서 결제요약·마감 전 체크리스트·원장 바로가기 (회계 사용 리포트 P1·P2)",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["account", "pumui_approval"],
    "data": [
        "security/ir.model.access.csv",
        "views/move_summary_views.xml",
        "views/checklist_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
