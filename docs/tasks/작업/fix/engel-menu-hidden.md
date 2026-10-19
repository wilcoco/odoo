# 작업: engel_injection(엥겔 구 연동) 메뉴 비노출

- 저장소: `wilcoco/odoo`
- 브랜치: `fix/engel-menu-hidden`
- 기준 브랜치/커밋: `18.0 / 1651c5b17bbd0940ebd572921a9e596038af3ac0`
- 요청: 사용자 직접 결정(2026-10-19) "일단은 놔두고, 메뉴에서 노출만 하지 마"
- 담당: Claude
- 상태: 검토 요청

## 목적과 범위

- 해결할 문제: `engel_injection`(엥겔 사출기 구 연동, `/api/v1/injection/*`)은 운영 데이터 0건(시리얼·설비 상태)이고 현장은 `injection_worksite` 경로를 쓴다. 같은 일을 하는 메뉴 「IATF 품질 > 사출 생산 관리」(시리얼 레코드·차종 관리·불량 유형·설비 상태)가 사용자에게 보여 혼동을 준다.
- 변경 범위: `addons_custom/engel_injection/views/menu.xml` 메뉴 5건 `active="False"`, 매니페스트 버전 18.0.1.0.2.
- 변경하지 않는 범위: 모델·API·권한·데이터. 모듈은 설치 상태 유지(제거·API 차단은 별도 결정).

## 통합 영향

- 상태 전이·수량·재고·LOT·정산·전표: 없음. 메뉴만 숨김. 액션·모델은 남아 있어 URL 직접 접근과 API 는 그대로다.
- 권한·회사 분리: 변화 없음.

## 변경 내용

- 변경 모듈/파일: `engel_injection/views/menu.xml`, `engel_injection/__manifest__.py`
- 설계 결정: 메뉴 레코드를 지우지 않고 비활성(`active=False`)으로 두어 되돌리기 쉽게 한다. 루트와 하위 4개 모두 비활성.
- 데이터/호환성: `-u engel_injection` 으로 메뉴 레코드가 갱신된다. `refactor/mold-master-single` 도 같은 모듈 버전을 18.0.1.0.2 로 올리므로 두 브랜치가 모두 병합되면 같은 값(충돌 없음).

## 정본·미러 대응

- 정본 커밋 및 경로: (커밋 후 기입) — `addons_custom/engel_injection`
- 미러 커밋 및 경로: 미반영. 병합 후 `escon-odoo/odoo_gh/iatf_plugins/engel_injection` 동기화 대상.
- 의도적 차이 또는 역반영 판정: 없음.

## 검증 증거

- DB/환경: 서버 격리 스택 DB `odoo18_auth_test`(2026-10-19 운영 덤프 복원·중립화), 운영 `27eee63` 런타임 + 이 브랜치 `engel_injection` 오버레이, 운영 무변경
- 실행 명령: `odoo -c test.conf -d odoo18_auth_test -u engel_injection --stop-after-init` (`refresh-20261020/engel-menu-upgrade.log`)
- 결과: 종료 코드 0, `ir_ui_menu` 의 engel_injection 메뉴 5건 모두 `active=false`, `latest_version 18.0.1.0.2`, IATF 루트의 다른 메뉴 유지.
- 미실행 검증과 이유: 화면 확인(메뉴 트리에서 사라짐은 `active` 로 보장). 이 모듈에는 자동 시험이 없다.

## 배포·롤백

- 모듈 업그레이드: `-u engel_injection`. 재기동 불필요(메뉴 캐시는 업그레이드로 갱신).
- 롤백: `active="False"` 제거 후 `-u engel_injection`, 또는 설정 > 기술 > 메뉴에서 활성화.
- 사람 승인: PR 검토·병합, 운영 반영.

## 남은 위험과 후속 작업

- 남은 위험: API 는 그대로 열려 있다(인증만, 권한 검사 없음). 접근 로그에서 `/api/v1/injection/` 호출이 없음을 확인한 뒤 차단·제거를 결정한다.
- PR 및 handoff 회신: (PR 생성 후 기입)
