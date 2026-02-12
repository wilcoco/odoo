{
    "name": "IATF Contingency Plan",
    "summary": "IATF 16949 §6.1.2.3 — Contingency plans for supply chain, equipment, labor disruptions",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/contingency_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
