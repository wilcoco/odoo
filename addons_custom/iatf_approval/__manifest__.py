{
    "name": "IATF Approval Workflow",
    "summary": "Reusable sequential approval workflow with notifications",
    "version": "18.0.1.1.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["base", "mail", "hr", "iatf_document_control"],
    "data": [
        "security/ir.model.access.csv",
        "data/approval_activity_type.xml",
        "views/approval_template_views.xml",
    ],
    "installable": True,
    "application": False,
}
