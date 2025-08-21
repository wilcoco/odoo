{
    "name": "MRP BOM Scan Guard",
    "summary": "Scan component barcode on Work Order and verify it matches the MO BOM (cross-check)",
    "version": "18.0.1.0.1",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["mrp", "stock", "web", "barcode_scanner_widget"],
    # odoo-qrcode(웹캠 위젯)을 쓰면 scan 필드가 카메라 스캔 UI로 보입니다.
    # 없으면 일반 입력(하드웨어 스캐너/키보드 웨지)로 동작합니다.
    "data": [
        "security/ir.model.access.csv",
        "views/mrp_bom_scan_guard_views.xml",
        "views/mrp_workorder_inherit_views.xml",
    ],
    "installable": True,
    "application": False,
}