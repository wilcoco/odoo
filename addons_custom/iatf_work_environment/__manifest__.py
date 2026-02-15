{
    "name": "IATF 작업환경 관리",
    "version": "18.0.1.0.0",
    "summary": "작업환경 모니터링, 5S 점검 (IATF 16949 §7.1.4)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "hr", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/work_environment_views.xml",
        "views/environment_check_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
