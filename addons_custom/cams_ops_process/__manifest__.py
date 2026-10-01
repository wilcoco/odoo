{
    "name": "회사 운영 센터",
    "version": "18.0.2.2.1",
    "summary": "역할별 업무 매뉴얼 + 주기 업무 자동생성 + 완료/승인 추적 — 초보자용 운영 가시화",
    "description": """
회사가 돌아가기 위한 역할별(회계·정산·원가·생산·사출·품질·조립·구매·경영) 업무를
정의(주기·기한·매뉴얼·대상 화면)하고, 주기마다 업무 건을 자동 생성해
'언제 무엇을 해야 하는지 / 되었는지 / 승인됐는지'를 한눈에 관리한다.
    """,
    "category": "Productivity",
    "license": "LGPL-3",
    "author": "CAMS",
    "depends": ["base", "mail", "web", "hr", "escon_hr_common", "escon_code"],
    "data": [
        "security/ops_security.xml",
        "security/ir.model.access.csv",
        "views/ops_views.xml",
        "views/employee_views.xml",
        "views/system_views.xml",
        "data/ops_cron.xml",
        "data/ops_seed.xml",
    ],
    "installable": True,
    "application": True,
    "icon": "cams_ops_process/static/description/icon.png",
}
