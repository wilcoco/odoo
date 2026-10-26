# 작업: 미러 PR #14(E7 직원 비공개 필드) 정본 역반영

- 저장소: `wilcoco/odoo`
- 브랜치: `sync/e7-employee-privacy`
- 기준 브랜치/커밋: `18.0 / 01f4035c442f`
- 요청: 사용자 지시(2026-10-26) "역반영 PR 만들어줘, 사라지지 않도록"
- 담당: Claude
- 상태: 검토 요청

## 목적과 범위

- 미러 `escon-odoo/odoo_gh` PR #14(`fix/e7-plan-close-20261021`, 커밋 cdc66e6e8, 2026-10-21 운영 배포됨)가 정본 모듈 `escon_eapproval` 을 미러에서 먼저 고쳤다. 정본 18.0 에 없으면 다음 정본→미러 동기화 때 덮어써 사라진다. 그 변경을 정본에 그대로 옮긴다.
- 변경 내용(미러와 바이트 동일): `hr.employee` 의 `eap_hire_date`(입사일)·`job_grade_id`(직급)에 `groups="hr.group_hr_user"` — 인사 권한이 없는 사용자(사출 반장 등)가 직원 공개 프로필을 읽을 때 이 필드가 prefetch 되어 "직원 공개 프로필에서 사용할 수 없습니다" 오류가 나던 것(시뮬레이션 E7 권한 공백)을 막는다. 시험 `tests/test_employee_privacy.py` 포함. 버전 18.0.6.1.1.
- 변경하지 않는 범위: 그 외 전부.

## 통합 영향

- 상태 전이·수량·재고·LOT·정산·전표: 없음.
- 권한·회사 분리: 입사일·직급은 인사 담당(hr.group_hr_user) 이상만 읽고 쓴다. 전자결재 "부서 내 직급자" 결재자 결정은 서버 권한으로 직급을 읽으므로 영향 없음(시험으로 확인).

## 정본·미러 대응

- 정본 커밋 및 경로: `b761a36dbd0a` + 이 문서 갱신 커밋 — `addons_custom/escon_eapproval/{__manifest__.py,models/annual_leave.py,models/job_grade.py,tests/}`
- 미러 커밋 및 경로: `odoo_gh` main `1c4d6bc48` (`iatf_plugins/escon_eapproval`) — 이미 운영 배포됨(2026-10-21). 역반영 후 정본·미러 동일.
- 의도적 차이 또는 역반영 판정: 역반영(미러 선행 수정). 미러 `scripts/e7_test/*` 와 작업 문서는 미러 전용이라 정본에 옮기지 않음.

## 검증 증거

- DB/환경: 서버 격리 스택 DB `odoo18_auth_test`, 정본 `escon_eapproval` 오버레이
- 실행 명령: `-u escon_eapproval --test-enable --test-tags /escon_eapproval` (`refresh-20261020/eap-backport-tests.log`)
- 결과: 운영 덤프를 새로 복원한 DB(`eap-backport-fresh.log`, `-u iatf_approval,escon_eapproval`) **21건 실패 0·오류 0**. (앞선 재사용 DB 1회 실행은 미리보기 잔여 데이터로 대시보드 KPI 시험 1건이 어긋났으나 새 DB에서 통과 — 코드 문제 아님)
EXIT 1 SECONDS 21 PROD_UNCHANGED True
- 미실행 검증과 이유: 운영 배포 — 이미 같은 코드가 운영 중(미러 경유).

## 배포·롤백

- 운영 배포 불필요(운영은 이미 이 코드). 병합 후 다음 미러 동기화 때 덮어쓰기 없음만 확인.
- 롤백: 해당 없음.

## 남은 위험과 후속 작업

- 미러에서 먼저 고치는 일이 반복되면 역반영 누락 위험 → 미러 PR 템플릿에 정본 대응 커밋 기입 확인.
- PR 및 handoff 회신: (PR 생성 후 기입)
