{
    'name': 'SCM 무발주 부품 공급 통보',
    'version': '18.0.1.1.0',
    'license': 'LGPL-3',
    'depends': ['supplier_portal_purchase', 'stock_account', 'purchase_stock'],
    'data': ['security/ir.model.access.csv', 'security/rules.xml', 'views/supply_views.xml', 'views/portal_templates.xml'],
    'installable': True,
    'auto_install': False,
    'application': False,
}
