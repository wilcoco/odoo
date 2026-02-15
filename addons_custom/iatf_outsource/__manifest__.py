{
    "name": "IATF 외주공정 관리",
    "version": "18.0.1.0.0",
    "summary": "외주공정 품질 관리 (IATF 16949 §8.4)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "purchase", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/outsource_process_views.xml",
        "views/outsource_order_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
