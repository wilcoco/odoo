{
    "name": "IATF SPC",
    "summary": "IATF 16949 §9.1.1.1 — Statistical Process Control (X-bar R, Cp/Cpk, control charts)",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "mrp", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/spc_study_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
