{
    "name": "IATF 품질 목표 관리",
    "version": "18.0.1.0.0",
    "summary": "품질 목표 및 KPI 관리 (IATF 16949 §6.2)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "stock", "iatf_document_control", "iatf_approval"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "data/cron.xml",
        "views/quality_objective_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
