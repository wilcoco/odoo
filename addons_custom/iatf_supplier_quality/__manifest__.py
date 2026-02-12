{
    "name": "IATF Supplier Quality",
    "summary": "IATF 16949 §8.4 — Supplier quality management, evaluation, and SCAR",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "stock", "purchase", "iatf_document_control", "iatf_nonconformity"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/supplier_evaluation_views.xml",
        "views/scar_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
