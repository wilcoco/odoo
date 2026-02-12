{
    "name": "IATF Calibration",
    "summary": "IATF 16949 §7.1.5 — Calibration & measurement equipment management",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "hr", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/calibration_views.xml",
        "views/equipment_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
