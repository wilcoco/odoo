{
    'name': 'SQ 서류 출력·일괄 업로드',
    'version': '18.0.1.0.0', 'license': 'LGPL-3',
    'depends': ['cams_sq', 'iatf_document_control', 'iatf_work_environment', 'cams_ops_process'],
    'data': ['security/security.xml', 'security/ir.model.access.csv',
             'reports/output.xml', 'views/output.xml'],
    'installable': True,
}
