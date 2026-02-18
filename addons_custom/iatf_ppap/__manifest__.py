{
    "name": "IATF PPAP",
    "summary": "IATF 16949 §8.3.4.4 — Production Part Approval Process (18 Elements, Level 1-5)",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "mrp", "iatf_document_control", "iatf_fmea", "iatf_control_plan"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/ppap_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
