{
    "name": "IATF FMEA",
    "summary": "IATF 16949 §8.3.5 — DFMEA / PFMEA with RPN & Action Priority calculation",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "iatf_document_control", "iatf_approval", "mrp"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/fmea_views.xml",
        "views/fmea_line_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
