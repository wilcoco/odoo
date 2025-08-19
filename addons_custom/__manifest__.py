{
    'name': "Barcode Scanner Widget",
    'version': '18.0.0.1',
    'depends': ['web'],
    'author': "DevSanx",
    'category': "Sales/Sales",
    'summary': 'Qrcode/Barcode Scanner',
    'description': """
        Scan Barcodes and Qrcodes using device camera
    """,
    'data': [
    ],
    'assets': {
        'web.assets_backend': [
            "addons_custom/static/src/css/webcam_qrcode_scan_styles.css",
            # Camera libraries (optional). Place the files under static/src/lib/ and uncomment the lines below.
            # "addons_custom/static/src/lib/html5-qrcode.min.js",
            # "addons_custom/static/src/lib/quagga.min.js",
            "addons_custom/static/src/js/barcode_scanner_widget.js",
        ],
        'web.assets_qweb': [
            "addons_custom/static/src/xml/webcam_qrcode_scan_template.xml",
        ],
    },
    'installable': True,
}