{
    'name': "Barcode Scanner Widget",
    'version': '18.0.0.2',
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
            # Optional camera libraries can be added under this module's static/src/lib/ if needed:
            # "barcode_scanner_widget/static/src/lib/html5-qrcode.min.js",
            # "barcode_scanner_widget/static/src/lib/quagga.min.js",
            "barcode_scanner_widget/static/src/js/barcode_scanner_widget.js",
        ],
        'web.assets_qweb': [
            "barcode_scanner_widget/static/src/xml/webcam_qrcode_scan_template.xml",
        ],
    },
    'installable': True,
}
