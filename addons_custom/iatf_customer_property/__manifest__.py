{
    "name": "IATF 고객재산 관리",
    "version": "18.0.1.0.0",
    "summary": "고객 지급품/재산 관리 (IATF 16949 §8.5.3)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/customer_property_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
