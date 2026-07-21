{
    "name": "한국 급여 (4대보험·간이세액)",
    "version": "18.0.2.1.0",
    "summary": "한국 급여 (생산직 매뉴얼 반영) — 일급제·통상/기타수당·상여650%분할·OT4종·EDI고지액·식대비과세·수습·퇴직급여. 수치는 전부 데이터",
    "category": "Human Resources/Payroll",
    "license": "LGPL-3",
    "author": "DevSanx",
    "depends": ["hr_payroll", "hr_attendance"],
    "data": [
        "security/ir.model.access.csv",
        "data/payroll_structure.xml",
        "data/rate_seed.xml",
        "views/rate_views.xml",
        "views/severance_views.xml",
        "views/contract_notice_views.xml",
        "views/attendance_views.xml",
    ],
    "installable": True,
}
