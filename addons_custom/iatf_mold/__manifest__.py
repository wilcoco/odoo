{
    "name": "IATF 금형/치공구 관리",
    "version": "18.0.2.0.0",
    "summary": "금형 마스터(injection.mold) 단일화 위의 IATF/SQ 금형관리 — 관리기준·점검·온도·시사출(T/O)·보전 (IATF 16949 §8.5.1.6)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    # iatf_process_inspection: 시사출 보고서의 초품 검사 연계(SQ 4_3)
    # injection_planning: 금형 마스터 injection.mold 를 정의한다(18.0.2.0.0 단일화).
    "depends": [
        "base", "mail", "mrp",
        "iatf_document_control", "iatf_approval", "iatf_process_inspection",
        "injection_planning",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/mold_views.xml",
        "views/mold_check_views.xml",
        "views/mold_temp_log_views.xml",
        "views/mold_tryout_views.xml",
        "views/mold_maintenance_views.xml",
        "views/mrp_production_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
