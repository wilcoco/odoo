{
    "name": "IATF Traceability",
    "summary": "IATF 16949 §8.5.2 — 로트/시리얼 추적성, 공정 이력, 리콜 시뮬레이션 + 분쇄·배합일지(SQ 1_10)",
    "version": "18.0.1.1.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    # iatf_equipment: 배합기·분쇄기를 설비 대장(iatf.equipment)에서 고른다.
    "depends": ["base", "mail", "stock", "mrp", "iatf_document_control",
                "iatf_nonconformity", "iatf_equipment"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/traceability_record_views.xml",
        "views/blend_views.xml",
        "views/recall_simulation_views.xml",
        "views/stock_lot_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
