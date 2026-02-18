{
    "name": "IATF 고객 특수요구사항 (CSR)",
    "version": "18.0.1.0.0",
    "summary": "고객별 특수요구사항 관리 (IATF 16949)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "sale", "iatf_document_control"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/csr_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
