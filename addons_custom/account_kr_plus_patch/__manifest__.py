{
    "name": "회계 한국식 통합 Plus Patch",
    "version": "18.0.2.5.0",
    "summary": "원화 금액 표시, 매입 화면, 한국식 전표번호, 은행계좌 연결",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "DevSanx",
    # sale: 마케팅(utm_link) 그룹, account_accountant: 변경 불가능 해시 노드 —
    # 둘 다 view_move_form_hide_unused_fields 의 xpath 대상이라 필수
    "depends": ["account_kr_reports", "sale", "account_accountant"],
    "data": [
        "data/decimal_precision.xml",
        "security/ir.model.access.csv",
        "data/kr_plus_settings_data.xml",
        "views/account_move_views.xml",
        "views/account_journal_views.xml",
        "views/account_move_hide_fields.xml",
        "views/sequence_repair_wizard_views.xml",
        "views/kr_plus_settings_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
}
