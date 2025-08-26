{
    'name': 'MRP Auto Order',
    'version': '18.0.1.0.0',
    'summary': 'Create and auto-confirm Manufacturing Orders from an order list',
    'category': 'Manufacturing',
    'depends': ['mrp'],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_auto_order_views.xml',
    ],
    'license': 'LGPL-3',
    'author': 'DevSanx',
    'installable': True,
    'application': False,
}
