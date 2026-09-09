{
    "name": "IATF Integrated Menu",
    "summary": "IATF 16949 통합 메뉴 — 전 모듈 액션을 9개 업무 카테고리로 재구성",
    "description": """
IATF 16949 통합 메뉴
====================
개별 iatf 모듈들의 액션을 경영/인적자원/품질시스템/생산/설비/구매/물류/안전/리포트
9개 카테고리 하위로 재배치한다.

타 모듈의 액션을 참조하므로 모든 iatf 모듈에 의존하며, 메뉴 골격(menu_iatf_root 등)은
iatf_document_control 모듈이 제공한다.
""",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": [
        "iatf_document_control",
        "iatf_dashboard",
        "iatf_management_review",
        "iatf_quality_objective",
        "iatf_contingency",
        "iatf_nonconformity",
        "iatf_training",
        "iatf_audit",
        "iatf_customer_complaint",
        "iatf_apqp",
        "iatf_ppap",
        "iatf_control_plan",
        "iatf_fmea",
        "iatf_spc",
        "iatf_incoming_inspection",
        "iatf_process_inspection",
        "iatf_layout_inspection",
        "iatf_equipment",
        "iatf_calibration",
        "iatf_work_environment",
        "iatf_mold",
        "iatf_supplier_quality",
        "iatf_outsource",
        "iatf_packaging",
        "iatf_traceability",
    ],
    "data": [
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
