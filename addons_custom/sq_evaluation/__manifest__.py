{
    "name": "SQ 평가 (협력사 품질 온사이트 평가)",
    "version": "18.0.1.0.0",
    "summary": "HKMC SQ 방식 협력사 품질 평가 — Odoo 실데이터 증빙 자동연동",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    # IATF 모듈에 하드의존하지 않음 — 증빙은 model in self.env 로 resilient 하게 조회
    "depends": ["base", "mail", "product", "stock", "hr"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/sq_category_data.xml",
        "data/sq_criteria_data.xml",
        "views/sq_evaluation_views.xml",
        "views/sq_criteria_views.xml",
        "views/sq_field_record_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": True,
}
