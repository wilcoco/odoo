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
    'data': [
    ],
    'assets': {
        'web.assets_backend': [
            "addons_custom/static/src/css/webcam_qrcode_scan_styles.css",
            # Camera libraries
            "addons_custom/static/src/lib/html5-qrcode.min.js",
            "addons_custom/static/src/lib/quagga.min.js",
            "addons_custom/static/src/js/barcode_scanner_widget.js",
        ],
        'web.assets_qweb': [
            "addons_custom/static/src/xml/webcam_qrcode_scan_template.xml",
        ],
    },
    'installable': True,
}