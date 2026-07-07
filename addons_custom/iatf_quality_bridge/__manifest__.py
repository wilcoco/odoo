{
    "name": "IATF ↔ Quality Control 브리지",
    "version": "18.0.1.0.0",
    "summary": "IATF 부적합 ↔ Odoo quality.alert 양방향 연결 (G2). enterprise quality 의존 — 옵션 설치.",
    "category": "Quality",
    "license": "LGPL-3",
    "author": "DevSanx",
    # 핵심 IATF 모듈은 enterprise 비의존 유지. 이 브리지만 quality_control 에 의존(옵션 설치).
    "depends": ["iatf_nonconformity", "quality_control"],
    "data": [
        "views/quality_bridge_views.xml",
    ],
    "installable": True,
    "application": False,
}
