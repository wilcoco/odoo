{
    'name': 'SQ',
    'summary': '사출·전기조립 SQ 기준, 준비 현황, 증빙 조회 및 자체 평가',
    'version': '18.0.1.3.0',
    'license': 'LGPL-3',
    'author': 'ESCON',
    'category': 'Quality',
    'depends': ['iatf_audit'],
    'data': ['security/security.xml', 'security/ir.model.access.csv', 'views/sq_views.xml', 'views/sq_approval_views.xml'],
    'application': True,
    'installable': True,
    'uninstall_hook': 'uninstall_hook',
}
