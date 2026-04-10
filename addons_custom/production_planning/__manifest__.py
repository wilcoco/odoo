{
    "name": "생산 계획 기준정보",
    "version": "18.0.1.0.0",
    "category": "Manufacturing",
    "summary": "전체 완제품 생산 수요 관리 (사출/외주/조립 공통)",
    "description": """
        생산 계획 기준 모듈
        ==================
        - 완제품 생산 수요 통합 관리
        - Oracle 연동 수요 데이터
        - 수동 수요 입력
        - 사출계획, 외주조달 등에서 공통 사용
    """,
    "author": "wilcoco",
    "depends": ["product", "mrp"],
    "data": [
        "security/ir.model.access.csv",
        "views/production_demand_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
