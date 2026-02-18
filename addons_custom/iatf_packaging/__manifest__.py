{
    "name": "IATF 포장/보존 관리",
    "version": "18.0.1.0.0",
    "summary": "포장 사양, 보존 조건 관리 (IATF 16949 §8.5.4)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "stock", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/packaging_spec_views.xml",
        "views/stock_picking_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
