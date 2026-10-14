{
    "name": "회계 한국식 비유동자산 확장 (Plus Patch · NC Asset)",
    "version": "18.0.1.0.0",
    "summary": "비상각(평가형) 자산, 토지 등 자산별 계정과목 자동 생성, 계약 단계(계약금·중도금·잔금) 계정, 재분류 초안 전표",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "DevSanx",
    # account_asset 은 엔터프라이즈 모듈이다. 이 모듈은 엔터프라이즈 환경 전용이며,
    # account_kr_plus_patch 와 account_asset 이 모두 설치된 DB에서 자동으로 함께 설치된다.
    "depends": ["account_kr_plus_patch", "account_asset"],
    "data": [
        "security/ir.model.access.csv",
        "views/res_company_views.xml",
        "views/account_asset_views.xml",
        "wizard/asset_reclass_wizard_views.xml",
    ],
    "auto_install": True,
    "installable": True,
}
