{
    "name": "IATF 도장 특화 시험",
    "version": "18.0.1.0.0",
    "summary": "도장/사출 특화 품질 시험 — 신뢰성·밀착성·색상·도막두께 (IATF 16949 §8.6)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "stock", "iatf_document_control", "iatf_nonconformity", "iatf_approval"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/coating_test_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
