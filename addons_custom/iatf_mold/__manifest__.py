{
    "name": "IATF 금형/치공구 관리",
    "version": "18.0.1.1.0",
    "summary": "금형, 치공구, 지그 관리 + 관리기준·시사출(T/O) (IATF 16949 §8.5.1.6)",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    # iatf_process_inspection: 시사출 보고서의 초품 검사 연계(SQ 4_3)
    "depends": [
        "base", "mail", "mrp",
        "iatf_document_control", "iatf_approval", "iatf_process_inspection",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequence.xml",
        "views/mold_views.xml",
        "views/mold_tryout_views.xml",
        "views/mold_maintenance_views.xml",
        "views/mrp_production_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
}
