{
    "name": "회계 금액 소수점 제거 패치 (K-Plus)",
    "version": "18.0.1.0.0",
    "summary": "digits 미지정 Float 금액 필드의 '.00' 표시 제거 — 원화 전용 설치본 (account_kr_guard 비침습 별도 패치)",
    "category": "Accounting",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["account"],
    "data": [
        "data/decimal_precision.xml",
    ],
    "installable": True,
}
