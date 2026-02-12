{
    "name": "IATF Internal Audit",
    "summary": "IATF 16949 §9.2 — Internal Audit management (System, Process, Product, VDA 6.3)",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "hr", "iatf_document_control", "iatf_nonconformity"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/audit_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
