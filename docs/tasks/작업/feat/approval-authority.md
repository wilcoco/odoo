# 작업: 자기결재 금지 + 전결 규정(문서별 결재 체계) 메뉴

- 저장소: `wilcoco/odoo`
- 브랜치: `feat/approval-authority`
- 기준 브랜치/커밋: `18.0 / 1651c5b17bbd0940ebd572921a9e596038af3ac0`
- 요청: 사용자 직접 결정(2026-10-19) "자기결재 금지 넣어줘. 전결 규정이 있어야 하고, 모든 결재를 나열하고 결재 체계를 입력·저장하는 메뉴가 있어야 한다"
- 담당: Claude (구현·서버 검증)
- 상태: 검토 요청

## 목적과 범위

- 해결할 문제: 결재 엔진(`iatf.approval`)이 작성자=결재자를 막지 않아 자기결재가 가능했다(운영에 이미 1건). 결재선 템플릿은 있으나 운영에 0건이고 "어떤 문서에 어떤 결재 체계를 쓰는지" 한눈에 보는 메뉴가 없었다.
- 변경 범위: `iatf_approval`(엔진·전결 규정 모델·화면·시험), `escon_eapproval`(전자결재 설정 메뉴·결재자 표시), 작성자=결재자였던 시험 fixture 3개(`iatf_incoming_inspection`, `iatf_process_inspection`).
- 변경하지 않는 범위: 각 문서 모듈의 결재 버튼·흐름, Odoo 표준 전자결재 앱(`approvals`)의 결재 유형, 운영 데이터.

## 통합 영향

- 상태 전이:
  - 상신 시 결재선에 작성(요청)자 또는 상신자가 있으면 `UserError`로 상신 거부(시스템 계정 제외). 결재 mixin 을 쓰는 27개 모듈(품의·정산 대사·가감·IQC·PQC·OQC·부적합·PPAP·금형·교정·FMEA·관리계획·심사·교육 등) 공통.
  - 전결 규정(`iatf.approval.policy`): 결재 문서마다 1행. `규정 필수`면 맞는 규정 없이는 상신 불가, `결재선 고정`이면 상신 시 수동 결재선을 규정으로 다시 구성.
  - 규정 결재자가 상신자 본인이면 그 단계는 빠지고, 남는 결재자가 없으면 상신 불가. "작성자의 부서장" 방식은 본인이 부서장이면 상위 부서장으로 올라간다.
- 수량·재고, LOT·시리얼, 납품·정산·전표: 없음(결재 통제만).
- 품질 승인·기록 보호: 결재 이력 보호(기존)는 그대로. 확정 실행 결과 기록은 승인 근거를 초기화하지 않는다.
- 권한·회사 분리: 전결 규정은 시스템 관리자·전자결재 관리자가 편집, 내부 사용자는 읽기. 템플릿 ACL 기존 유지.

## 변경 내용

- 변경 모듈/파일:
  - `iatf_approval` 18.0.1.3.0
    - `models/approval_guard.py`: `_validate_approvers(submitter)` + `_check_self_approval` — 요청자·상신자 ∉ 결재선
    - `models/approval_policy.py`(신규): `iatf.approval.policy` — 결재 문서 자동 나열(`_sync_documents`, mixin 사용 모델 레지스트리 조회), 규정 필수/결재선 고정, 결재 건수
    - `models/approval_template.py`: 템플릿 ↔ 규정 연결(`policy_id`, 모델 자동 일치), 결재 순서 요약, 전결 규정표용 관련 필드, 부서장 방식 상위 부서 승격
    - `models/approval_request.py`: `_approval_apply_default_template` — 규정 필수·고정·본인 단계 제외
    - `views/approval_policy_views.xml`(신규): 전결 규정(목록·폼·검색), 전결 규정표(문서×조건×순서×결재자, 엑셀 내보내기용), 메뉴(설정 > 기술) — 메뉴를 열 때 새 결재 문서를 자동 추가
    - `views/approval_template_views.xml`: 템플릿에 전결 규정 필드
    - `security/ir.model.access.csv`: policy 읽기(내부)/관리(시스템 관리자)
    - `tests/test_approval_authority.py`(신규 9건): 작성자·상신자 결재 금지, 정상 결재 유지, 문서 나열·중복 없음, 부서장 승격, 본인 단계 제외, 결재선 고정, 규정 필수, 규정표
  - `escon_eapproval` 18.0.6.1.0: 전자결재 > 설정에 「전결 규정」「전결 규정표」 메뉴, 전자결재 관리자 ACL, 직급·지정 부서 방식 결재자 표시
  - 시험 fixture(작성자=결재자였던 것): `iatf_incoming_inspection/tests/test_iqc_gate.py`(검사자와 별도 승인자), `hold_release_fixture.py`(요청자=자재 담당, 승인=품질·생산), `iatf_process_inspection/tests/test_outgoing_gate.py`(상신=검사 담당, 승인=승인자)
- 설계 결정:
  - 금지 범위는 "요청자와 상신자". 결재 중 다른 사람이 문서를 고쳐도 승인자 자격은 바뀌지 않는다.
  - 전결 규정은 기존 결재선 템플릿을 그릇으로 쓴다(새 결재 엔진 없음). 규정 1행 = 템플릿 1건이며 문서 모델은 규정의 문서로 고정.
  - 결재 문서 목록은 코드 레지스트리에서 자동으로 뽑는다(수작업 목록 없음). 새 모듈이 설치되면 메뉴를 열 때 추가된다.
- 데이터/호환성: 기존 결재 요청·템플릿 무변경. 운영 전결 규정은 설치 직후 "규정 없음" 상태(= 지금과 같은 수동 결재선). 운영에 있는 자기결재 1건은 이력으로 남고 새 상신부터 적용.

## 정본·미러 대응

- 정본 커밋 및 경로: (커밋 후 기입) — `addons_custom/{iatf_approval,escon_eapproval,iatf_incoming_inspection/tests,iatf_process_inspection/tests}`
- 미러 커밋 및 경로: 미반영. 병합 후 `escon-odoo/odoo_gh/iatf_plugins/` 동기화 대상. 미러 전용 `gh_vendor_settlement` 시험 fixture(작성자=결재자)는 미러 브랜치 `fix/approval-self-check-tests` 에서 함께 고친다.
- 의도적 차이 또는 역반영 판정: 없음.

## 검증 증거

- 코드 커밋: (커밋 후 기입)
- DB/환경: 운영 서버 10.10.21.20 격리 시험 스택, DB `odoo18_auth_test`(2026-10-19 운영 덤프 복원·중립화), 실행 코드 = 운영 `27eee63` 런타임 + 이 브랜치 모듈 오버레이(`refresh-20261020/runtime-auth`), 운영 컨테이너 무변경
- 실행 명령(서버 `claude_auth_test.py`):
  - 1차: `-u iatf_approval,escon_eapproval --test-enable --test-tags /iatf_approval,/escon_eapproval` → `auth-tests1.log` **54건 실패 0·오류 0**(신규 9 포함)
  - 회귀(결재 mixin 에 의존하는 설치 모듈 39개): `-u iatf_approval,escon_eapproval --test-enable --test-tags /account_kr_guard,…,/pumui_approval`
- 결과 및 로그/산출물(서버 `/db/codex-testdb/odoo18-test-20261015/refresh-20261020/`):
  - 운영 코드 기준 `auth-regression-base.log`: 805건 중 오류 8(`TestRetroSettlement` — 대사 규칙 이전 시험, 이번 변경과 무관)
  - 1차 회귀 `auth-regression-branch.log`: 814건 중 오류 98 — 90건이 **시험 fixture 의 자기결재**(IQC 18, 출하 게이트 26, 정산 대사·가감·품의 43 등)에서 새 금지에 걸린 것. 제품 결함 아님 → fixture 를 "작성자≠결재자"로 수정
  - 2차 회귀 `auth-regression-branch2.log`: (기입)
- 미실행 검증과 이유: 화면(브라우저) 조작, 실사용자 부서장·직급 연결(운영 계정 3개뿐).

## 배포·롤백

- 모듈 업그레이드/마이그레이션: `-u iatf_approval,escon_eapproval` (하위 의존 모듈 자동 포함). 마이그레이션 없음.
- 재기동 및 확인: 전자결재 > 설정 > 전결 규정에 결재 문서가 나열되는지, 품의 상신 시 결재선에 본인이 있으면 거부되는지.
- 롤백 조건/방법: 상신이 광범위하게 막히면 이전 코드로 되돌리고 같은 모듈 `-u`. 전결 규정 데이터는 템플릿 테이블에 남지만 무해.
- 사람 승인: PR 검토·병합, 운영 전결 규정 입력(부서장·직급 연결 후), 운영 반영 각각.

## 남은 위험과 후속 작업

- 남은 위험: 실사용자 개인 계정이 생기기 전에는 규정의 "부서장/직급" 결재자가 결정되지 않아 수동 결재선을 계속 쓴다. 전자결재 앱(초과근무·출장 등 16종)은 '직속 상사 승인'이라 직원의 상사 연결이 필요하다(AP9).
- 미해결/후속: 미러 동기화 + `fix/approval-self-check-tests` 병합, 운영 전결 규정 초안(부서장 → 대표, 금액 기준) 입력, 자기결재 이력 1건 검토.
- PR 및 handoff 회신: (PR 생성 후 기입)
