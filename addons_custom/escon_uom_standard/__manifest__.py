{
    "name": "단위 기준 (UoM Standard)",
    "version": "18.0.1.0.0",
    "summary": "전사 단위 기준 정책 마스터 + 전 영역 정합 점검 (BOM 원단위 g, 재고 kg 등 — 기준은 데이터, 위반은 드릴다운)",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["mrp", "uom", "injection_planning"],
    "data": [
        "security/ir.model.access.csv",
        "data/policy_seed.xml",
        "views/views.xml",
    ],
    "installable": True,
}
