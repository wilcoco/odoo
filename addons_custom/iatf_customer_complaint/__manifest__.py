{
    "name": "IATF Customer Complaint",
    "summary": "IATF 16949 §10.2.6 — Customer complaint management, warranty, field return tracking",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "stock", "iatf_document_control", "iatf_nonconformity"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/complaint_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
