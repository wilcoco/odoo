{
    "name": "IATF 출하검사",
    "version": "18.0.1.0.0",
    "summary": "출하검사 관리 (IATF 16949 §8.6) — 포장·라벨 검사 포함",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "stock", "iatf_document_control", "iatf_nonconformity", "iatf_approval"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/shipping_inspection_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
