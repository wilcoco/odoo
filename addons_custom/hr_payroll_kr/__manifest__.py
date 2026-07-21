{
    "name": "한국 급여 (4대보험·간이세액)",
    "version": "18.0.1.0.0",
    "summary": "한국 표준 급여 구조 — 4대보험 요율·간이세액표를 유효기간 마스터로 관리 (요율은 데이터, 코드에 수치 없음)",
    "category": "Human Resources/Payroll",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["hr_payroll"],
    "data": [
        "security/ir.model.access.csv",
        "data/payroll_structure.xml",
        "data/rate_seed.xml",
        "views/rate_views.xml",
    ],
    "installable": True,
}
