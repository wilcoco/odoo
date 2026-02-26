{
    "name": "CAMS Branding",
    "summary": "CAMS ERP branding for website and web client",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "license": "LGPL-3",
    "depends": ["web", "website"],
    "data": [
        "views/website_branding.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "cams_branding/static/src/js/title_brand_service.js",
        ],
    },
    "installable": True,
    "application": False,
}
