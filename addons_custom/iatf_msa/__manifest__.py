{
    "name": "IATF MSA",
    "summary": "IATF 16949 §7.1.5.1.1 — Measurement System Analysis (Gage R&R, Bias, Linearity)",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/msa_study_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
