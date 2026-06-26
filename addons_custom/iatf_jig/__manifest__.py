{
    "name": "IATF 지그/공정 마스터",
    "version": "18.0.1.0.0",
    "summary": "지그(Jig) 대장·점검 기록 + 공정(Process) 마스터 (IATF 16949)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "product", "hr", "iatf_document_control", "iatf_approval", "mrp"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/jig_views.xml",
        "views/process_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
