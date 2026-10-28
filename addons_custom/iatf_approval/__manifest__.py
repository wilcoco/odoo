{
    "name": "IATF Approval Workflow",
    "summary": "Reusable sequential approval workflow with notifications",
    "version": "18.0.1.3.2",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "hr", "iatf_document_control"],
    "data": [
        "security/ir.model.access.csv",
        "security/approval_rules.xml",
        "views/approval_evidence_views.xml",
        "data/approval_activity_type.xml",
        "views/approval_template_views.xml",
        "views/approval_policy_views.xml",
    ],
    "installable": True,
    "application": False,
}
