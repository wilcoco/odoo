{
    "name": "IATF 레이아웃 검사",
    "version": "18.0.1.0.0",
    "summary": "레이아웃 검사 / 기능 시험 (IATF 16949 §8.6.2)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/layout_inspection_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
