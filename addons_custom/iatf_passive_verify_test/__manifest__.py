{
    'name': 'IATF 패스 검증 · 로그',
    'version': '18.0.1.0.0',
    'summary': 'IATF 업무 차단을 관찰 로그로 전환하는 회사별 시험 모드',
    'category': 'Quality',
    'license': 'LGPL-3',
    'depends': [
        'iatf_process_inspection', 'iatf_incoming_inspection', 'iatf_approval',
        'iatf_change_management', 'iatf_training', 'iatf_mold',
        'iatf_traceability', 'iatf_ppap', 'iatf_control_plan', 'iatf_packaging',
    ],
    'data': ['security/security.xml', 'security/ir.model.access.csv', 'views/passive_views.xml'],
    'application': True,
    'installable': True,
}
