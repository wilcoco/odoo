# 사내 CI (wilcoco repo)

odoo_gh 의 사내 CI 러너와 동일 절차 (원본: odoo_gh/ci, 1번 세션 작성).

- `run_tests.sh <모듈,콤마목록>` — 신선 DB 설치 + 회귀 테스트 (로컬 docker 스택 필요)
  - 회계·급여·품의: `ci/run_tests.sh pumui_approval,account_kr_guard,account_kr_reports,hr_payroll_kr`
  - 계획·연동: `ci/run_tests.sh erp_plan_sync,injection_planning`
  - IATF 검사: `ci/run_tests.sh iatf_process_inspection,iatf_incoming_inspection`
- `merge_integrity_check.sh <base-ref> [branch...]` — 머지 후 심볼 생존·커밋 포함 여부·시험 머지
- `critical_symbols.txt` — 이 repo 의 생존 필수 심볼. 기능 추가 시 갱신.
