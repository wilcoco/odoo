{
    "name": "IATF 변경 관리",
    "version": "18.0.1.0.0",
    "summary": "4M 변경 관리 (IATF 16949 §8.5.6)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "hr", "mrp", "iatf_document_control", "iatf_nonconformity"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/change_request_views.xml",
        "views/mrp_bom_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
