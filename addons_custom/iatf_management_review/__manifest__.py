{
    "name": "IATF Management Review",
    "summary": "IATF 16949 §9.3 — Management Review meetings, inputs/outputs, action items",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/management_review_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
