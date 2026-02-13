{
    "name": "IATF 공정검사 / 최종검사",
    "version": "18.0.1.0.0",
    "summary": "공정검사 및 최종검사 관리 (IATF 16949 §8.6)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "mrp", "stock", "iatf_document_control", "iatf_nonconformity"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/process_inspection_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
