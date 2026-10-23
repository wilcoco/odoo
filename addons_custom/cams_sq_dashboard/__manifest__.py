{'name': 'SQ 준비·운영 현황',
 'version': '18.0.1.3.1',
 'license': 'LGPL-3',
 'depends': ['cams_sq', 'cams_ops_process', 'iatf_incoming_inspection', 'iatf_shipping_inspection', 'iatf_work_environment'],
 'data': ['security/security.xml', 'views/dashboard.xml', 'views/daily.xml', 'views/receipt.xml'],
 'assets': {'web.assets_backend': ['cams_sq_dashboard/static/src/dashboard.js',
                                   'cams_sq_dashboard/static/src/dashboard.xml',
                                   'cams_sq_dashboard/static/src/dashboard.scss']},
 'installable': True}
