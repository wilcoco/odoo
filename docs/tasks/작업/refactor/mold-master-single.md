# 작업: 금형 마스터 injection.mold 단일화

- 저장소: `wilcoco/odoo`
- 브랜치: `refactor/mold-master-single`
- 기준 브랜치/커밋: `18.0 / 1651c5b17bbd0940ebd572921a9e596038af3ac0`
- 요청: 사용자 직접 요청(2026-10-19) "금형 마스터는 injection.mold 기준으로 단일화" + 순서 조정 의견(별도 브랜치 push → 전체 회귀 통과 시 PR → 검토 후 8070 반영·A4/G2 재시험)
- 담당: Claude (구현·서버 검증)
- 상태: 검토 요청

## 목적과 범위

- 해결할 문제: 운영에 금형 마스터가 두 벌. 생산계획·사출 현장·PLC 샷은 `injection.mold`(운영 18건), SQ 금형관리(점검·세척·예열/온도·시사출·보전)는 별도 `iatf.mold`(운영 0건)에 붙어 있어 같은 금형을 두 대장에 입력해야 하고, SQ 기록이 생산 금형과 연결되지 않는다(SQ 4_1·4_2·4_5·4_6·4_7, 130점 영역).
- 변경 범위: `iatf_mold`(모델·화면·권한·마이그레이션·시험), `engel_injection`(시리얼 금형 링크), `iatf_dashboard`(금형 집계), `escon_eapproval` 시험, `addons_custom/CLAUDE.md` 규칙.
- 변경하지 않는 범위: `injection_planning` 모델·화면 원본, 미러 전용 모듈(`injection_worksite`·`injection_mold_temperature`·`escon_code_viewer`), IATF→SQ 메뉴 재배치(가동 뒤로 연기).

## 통합 영향

- 상태 전이: 금형 상태에 `draft(등록)`·`inactive(비사용)` 추가, 폐기는 기존 `retired`(예전 iatf `disposed`). 기본값 `active` 유지 → 생산계획·현장 금형 목록 동작 동일.
- 수량·재고: 없음. 샷 수(`current_shots`)는 현장 API 가 계속 누적하고, `iatf_mold` 의 MO 완료 누적은 사출 현장 MO(`is_injection_mo`)에서 건너뛰어 이중 누적을 막는다.
- LOT·시리얼 추적: 엥겔 시리얼 `mold_id` → `injection.mold`.
- 품질 승인·기록 보호: 금형 대장 결재(`iatf.approval.mixin`)를 `injection.mold` 로 이동. 샷 누적·계획 예약·운영 상태 전환은 결재 초기화 대상에서 제외, 관리기준 변경은 초기화. 점검·시사출의 `ondelete=restrict` 유지.
- 납품·정산·전표: 없음.
- 권한·회사 분리: 금형관리 담당자/관리자에게 `injection.mold` 읽기·쓰기(관리자 삭제) 부여. `injection_planning` 의 회사 규칙 그대로.

## 변경 내용

- 변경 모듈/파일: `addons_custom/iatf_mold/**`, `addons_custom/engel_injection/{models/injection_serial.py,__manifest__.py,CLAUDE.md}`, `addons_custom/iatf_dashboard/{models/dashboard.py,__manifest__.py}`, `addons_custom/escon_eapproval/tests/test_eapproval.py`, `addons_custom/CLAUDE.md`
- 설계 결정:
  - `iatf.mold` 폐지, `iatf_mold` 가 `_inherit = ["iatf.approval.mixin", "injection.mold"]` 로 확장(믹스인을 앞에 — 둘 다 mail.thread 상속이라 순서가 뒤면 MRO 실패, 커밋 551f393).
  - 화면은 `injection_planning` 금형 목록·폼·검색 **상속**. IATF 「금형 대장」 메뉴 = `injection_planning.action_injection_mold`(같은 액션).
  - 수명 사용률·잔여 샷은 비저장 계산 + SQL 검색(현장 SQL 샷 증가에 저장값이 굳어 수명 경고가 안 뜨는 문제 방지).
  - 금형 코드는 사람이 정하는 코드(필수). 코드 없이 ORM 생성 시에만 기존 `MD-` 채번.
- 데이터/호환성: `migrations/18.0.2.0.0/pre-migration.py` — `iatf_mold` 에 행이 있으면 업그레이드 중단(자동 매칭 안 함), 0건이면 `iatf_mold` 를 가리키던 외래키 제거 후 ORM 이 `injection_mold` 로 재생성. 운영(odoo18)·WSL(esconodoo202609) 모두 0건 확인(2026-10-19).

## 정본·미러 대응

- 정본 커밋 및 경로: `0c2f37b`(단일화), `551f393`(MRO 수정) — `addons_custom/{iatf_mold,engel_injection,iatf_dashboard,escon_eapproval}`
- 미러 커밋 및 경로: 미반영. 병합 후 `escon-odoo/odoo_gh/iatf_plugins/` 동일 4개 모듈 동기화 대상.
- 의도적 차이 또는 역반영 판정: 미러 전용 `escon_code_viewer` 의 `iatf.mold` 대상 목록(미설치 모듈)과 `injection_worksite` 금형 목록 API 의 금형 유형 필터는 후속(미러 작업)으로 분리.

## 검증 증거

- 코드 커밋: `551f393e0cf7843a969ffd702071e50d01848a41` (서버 실행 코드 = 운영 미러 `27eee638` + 위 4개 모듈 오버레이)
- DB/환경: 운영 서버 10.10.21.20 격리 시험 스택 `escon-odoo18-test-pg`, DB `odoo18_mold_test`(2026-10-19 운영 odoo18 덤프 복원·중립화), 이미지 `sha256:59eff15a…`(운영 동일), Odoo 18 Enterprise
- 실행 명령:
  - 업그레이드: `odoo -c test.conf -d odoo18_mold_test -u iatf_mold --stop-after-init` (서버 스크립트 `refresh_20261020.py upgrade`)
  - 1차 시험: `-u iatf_mold,engel_injection,iatf_dashboard,escon_eapproval --test-enable --test-tags /iatf_mold,/engel_injection,/iatf_dashboard,/escon_eapproval`
  - 전체 회귀: `-u iatf_mold,engel_injection,iatf_dashboard,escon_eapproval,iatf_menu,injection_planning,injection_worksite,injection_mold_temperature,injection_costing --test-enable --test-tags` 동일 9개 모듈
- 결과 및 로그/산출물(서버 `/db/codex-testdb/odoo18-test-20261015/refresh-20261020/`):
  - 업그레이드 `upgrade.log`: 1회차 MRO 오류로 레지스트리 로드 실패(트랜잭션 롤백, DB 무변경) → 551f393 수정 후 성공. `iatf_mold` 2.0.0, `engel_injection` 1.0.2, `iatf_dashboard` 1.0.1. `ir_model` 의 `iatf.mold` 0건, 점검·스냅샷·온도·시사출·보전·MO·엥겔 시리얼 외래키 → `injection_mold`.
  - 1차 시험 `tests.log`: **116건 실패 0·오류 0**.
  - 전체 회귀 `mold-regression.log`: 771건 중 실패 9·오류 2 — 전부 `injection_worksite` 의 HTTP 시험(`TestWorksiteBearerSecurity` 9, `TestInjectionApiLog` setUpClass 2). 원인: 시험용 설정 파일의 `db_name/dbfilter=^odoo18_test$` 때문에 HTTP 요청이 다른 DB(odoo18_test)로 가서 `401 Invalid apikey`·`KeyError: 'odoo18_test'`. 코드 결함 아님.
  - 재시험 `mold-regression2.log`(DB 고정값을 odoo18_mold_test 로 맞춘 `mold-test.conf`, `-u injection_worksite --test-tags /injection_worksite:TestWorksiteBearerSecurity,/injection_worksite:TestInjectionApiLog`): **11건 실패 0·오류 0**.
  - 종합: 9개 모듈 전체 회귀 771건 — 760건 1차 통과 + 환경 원인 11건 재시험 통과 = **전부 통과**.
- 미실행 검증과 이유: 화면(브라우저) 확인, 실물 PLC 샷 누적, 미러 전용 모듈과의 통합(동기화 전).

## 배포·롤백

- 모듈 업그레이드/마이그레이션: `-u iatf_mold`(하위 의존 engel_injection·iatf_dashboard·iatf_menu 자동 포함). 사전 확인: `select count(*) from iatf_mold` = 0.
- 재기동 및 확인: 모델 제거·추가가 있어 업그레이드 후 재기동. 확인 항목 — 금형 대장/금형 관리 메뉴가 같은 목록, 점검·시사출 생성, 생산계획 계산, 현장 금형 목록 API.
- 롤백 조건/방법: 업그레이드 실패 시 트랜잭션 자동 롤백(DB 무변경 확인됨). 반영 후 문제 시 업그레이드 직전 DB 덤프 복원 + 이전 코드.
- 사람 승인: PR 검토·병합, 8070 반영, 운영 반영 각각 별도 승인.

## 남은 위험과 후속 작업

- 남은 위험: 빈 `iatf_mold` 테이블이 남는다(무해, 정리 대상). 금형 대장에 지그·게이지 등 비사출 유형을 등록하면 현장 금형 목록 API(`state=active`)에 나타날 수 있다 — 미러 `injection_worksite` 에 유형 필터 추가 필요.
- 미해결/후속: 미러 동기화, `escon_code_viewer` 대상 갱신, MO 의 금형 필드 2개(`mold_id` iatf / `actual_mold_id` 현장) 정리, `injection_mold_temperature`(20점 기준)와 iatf 예열·금형온도 상하한 기준 통합.
- PR 및 handoff 회신: (PR 생성 후 기입)
