{
    "name": "IATF 수입검사",
    "version": "18.0.1.0.0",
    "summary": "수입검사 관리 (IATF 16949 §8.6.4)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "stock", "purchase", "iatf_document_control", "iatf_nonconformity"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/incoming_inspection_views.xml",
        "views/inspection_criteria_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
