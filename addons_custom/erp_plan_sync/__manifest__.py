{
    "name": "ERP 생산계획 연동 (Oracle)",
    "version": "18.0.1.0.0",
    "summary": "자동차 ERP(오라클) T_ZM_PLN2 일자별 생산계획 수신 → 품번 매칭 → 생산 수요(production.demand) 반영. 접속정보는 시스템 파라미터로만.",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["production_planning", "injection_planning"],
    "external_dependencies": {"python": ["oracledb"]},
    "data": [
        "security/ir.model.access.csv",
        "views/erp_plan_views.xml",
        "data/cron.xml",
    ],
    "installable": True,
}
