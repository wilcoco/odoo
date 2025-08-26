{
    'name': "Barcode Scanner Widget",
    'version': '18.0.0.7',
    'depends': ['web'],
    'author': "DevSanx",
    'license': 'LGPL-3',
    'category': "Tools",
    'summary': 'Qrcode/Barcode Scanner',
    'description': """
        Scan Barcodes and Qrcodes using device camera
    """,
    'application': True,
    'data': [],
    'assets': {
        'web.assets_backend': [
            "barcode_scanner_widget/static/src/css/webcam_qrcode_scan_styles.css",
            # Camera libraries (consolidated here)
            "barcode_scanner_widget/static/src/lib/html5-qrcode.min.js",
            "barcode_scanner_widget/static/src/lib/quagga.min.js",
            # OWL field widget + QWeb template (Odoo 17/18: include xml in backend bundle)
            "barcode_scanner_widget/static/src/js/barcode_scanner_field.js",
            "barcode_scanner_widget/static/src/xml/webcam_qrcode_scan_template.xml",
        ],
    },
    'installable': True,
}
