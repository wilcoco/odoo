{
    "name": "회계 한국식 통합 Plus Patch",
    "version": "18.0.2.1.0",
    "summary": "원화 금액 표시, 매입 화면, 한국식 전표번호, 은행계좌 연결",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["account_kr_reports"],
    "data": [
        "data/decimal_precision.xml",
        "security/ir.model.access.csv",
        "views/account_move_views.xml",
        "views/account_journal_views.xml",
        "views/kr_plus_settings_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
