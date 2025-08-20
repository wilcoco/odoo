{
    'name': "Custom Assets (legacy)",
    'version': '18.0.0.3',
    'depends': ['web'],
    'author': "DevSanx",
    'license': 'LGPL-3',
    'category': "Tools",
    'summary': 'Qrcode/Barcode Scanner',
    'description': """
        Scan Barcodes and Qrcodes using device camera
    """,
    'application': False,
    'data': [
    ],
    # Legacy module: no assets bundled (migrated to barcode_scanner_widget)
    'assets': {
        'web.assets_backend': [],
        'web.assets_qweb': [],
    },
    'installable': True,
}