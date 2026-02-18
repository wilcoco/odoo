{
    "name": "IATF 금형/치공구 관리",
    "version": "18.0.1.0.0",
    "summary": "금형, 치공구, 지그 관리 (IATF 16949 §8.5.1.6)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "mrp", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/mold_views.xml",
        "views/mold_maintenance_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
