{
    "name": "회계 한국식 차입금 확장 (Plus Patch · Loans)",
    "version": "18.0.1.0.0",
    "summary": "차입금 기준정보 전용 모드, 대주·이자율·차환 연결, 실제 전표 대조 (엔터프라이즈 차입금 관리 확장)",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "DevSanx",
    # account_loans 는 엔터프라이즈 모듈이다. 이 모듈은 엔터프라이즈 환경 전용이며,
    # account_kr_plus_patch 와 account_loans 가 모두 설치된 DB에서 자동으로 함께 설치된다.
    "depends": ["account_kr_plus_patch", "account_loans"],
    "data": [
        "security/ir.model.access.csv",
        "views/account_loan_views.xml",
    ],
    "auto_install": True,
    "installable": True,
}
