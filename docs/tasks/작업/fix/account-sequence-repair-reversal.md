# 작업: 전표번호 소급 마법사 연결 및 역분개 공통 순번

- 저장소: `wilcoco/odoo`
- 브랜치: `fix/account-sequence-repair-reversal`
- 기준 브랜치/커밋: `fix/account-krw-amount-digits` / `96c12f942e376136cad70843c20eb9bbad2ac404`
- 요청: 사용자 직접 요청(2026-09-13)
- 담당: Codex
- 상태: `배포 대기`

## 목적과 범위

- 해결할 문제:
  - `전표번호 소급 변경 적용`에서 `대상 찾기 및 미리보기` 실행 후 모달이 닫혀
    미리보기와 적용 단계가 이어지지 않는 문제를 해결한다.
  - 마법사의 `대상 저널` 표시명을 `대상 전표`로 바꾼다.
  - 한국식 전표번호에서 역분개 `R`을 별도 순번 그룹으로 취급하지 않고 정상 전표와
    회사·전표일자별 6자리 순번을 공유하게 한다.
- 변경 범위: `account_kr_plus_patch`의 신규 채번, 소급 변경 마법사, 순번 공백 판정,
  사용자 문서와 회귀 테스트.
- 변경하지 않는 범위: 기존 전표번호 일괄 마이그레이션, 회계 금액·분개 라인·세금·결제,
  Odoo 코어 및 다른 모듈, 운영 DB와 운영 서버.

## 통합 영향

- 상태 전이: 전표의 draft/posted/cancel 상태 전이는 바꾸지 않는다. 마법사 자체는
  검색 후 `preview`, 적용 후 `done` 상태로 전환되며 같은 transient 레코드의 모달을
  다시 열어 다음 단계를 표시한다.
- 수량·재고: 영향 없음.
- LOT·시리얼 추적: 영향 없음.
- 품질 승인·기록 보호: 영향 없음. 해시 보호 전표와 잠긴 회계기간 전표의 기존 변경
  차단을 유지한다.
- 납품·정산·전표: 한국식 번호 규칙을 사용하는 회사에서 신규 정상/역분개 전표가
  회사·전표일자별 하나의 순번을 공유한다. 예: `...000001GEN`, `...000002SAL`,
  `R...000003SAL`, `...000004GEN`. `R`과 `TTT`는 표시만 담당한다.
- 권한·회사 분리: 기존 회계 관리자 검사와 회사 도메인을 유지한다. 회사별 순번은
  분리되며 다른 회사 전표를 조회·변경하지 않는다.

## 변경 내용

- 변경 모듈/파일:
  - `addons_custom/account_kr_plus_patch/models/account_move.py`
  - `addons_custom/account_kr_plus_patch/models/sequence_repair_wizard.py`
  - `addons_custom/account_kr_plus_patch/tests/test_account_kr_plus_patch.py`
  - `addons_custom/account_kr_plus_patch/__manifest__.py`
  - `addons_custom/account_kr_plus_patch/README.md`
  - `addons_custom/account_kr_plus_patch/docs/ACCOUNTING_USER_GUIDE_KO.md`
- 설계 결정:
  - 신규 번호의 최댓값 조회 정규식을 `R?YYYYMMDDNNNNNN(TTT)`로 통합하고,
    PostgreSQL advisory lock도 회사·일자 하나로 통합하여 정상/역분개 동시 전기 때
    같은 번호가 발급되지 않게 한다.
  - 순번 공백 판정도 prefix가 아닌 회사·일자를 기준으로 하여 정상/역분개가 번갈아
    발급될 때 거짓 공백 경고가 생기지 않게 한다.
  - 소급 마법사의 중복 키와 재채번 그룹에서 정상/역분개 구분을 제거하되, 출력 이름의
    `R`은 전표 유형에 따라 그대로 유지한다.
  - `action_scan`, `action_reset`, `action_apply`가 `False` 대신 동일 wizard `res_id`의
    `ir.actions.act_window(target="new")`를 반환하게 한다.
- 데이터/호환성:
  - 모듈 버전은 `18.0.2.5.4`다.
  - 마이그레이션 파일은 추가하지 않는다. 업그레이드만으로 기존 번호를 바꾸지 않는다.
  - 기존 정상/역분개가 같은 날짜·순번을 각각 사용했다면 신규 채번은 양쪽 최댓값 다음
    번호부터 이어지고, 사용자가 소급 마법사를 실행할 때만 후순위 중복 번호를 변경안으로
    제시한다.
  - 정상 전표와 역분개만 따로 조회하면 번호가 건너뛰어 보일 수 있으나 회사·일자 전체
    원장에서는 연속 번호다. 외부 연계가 `R` 번호만 별도 연속이라고 가정했다면 수정이
    필요하다.

## 정본·미러 대응

- 정본 커밋 및 경로:
  - 기능 커밋 `013c189d704fb097c4e46db8af4e7ecabfc0a852`
  - `wilcoco/odoo:addons_custom/account_kr_plus_patch`
- 미러 커밋 및 경로:
  - 공식 로컬 정본 동기화 커밋
    `74d4677a7340fc4b8acb63558cc45e86c6ad3107`
  - 대상 경로 `escon-odoo/odoo_gh:iatf_plugins/account_kr_plus_patch`
- 의도적 차이 또는 역반영 판정:
  - 의도적 파일 차이는 허용하지 않는다. 모듈 전체가 정본과 `diff 0`이어야 한다.
  - 직접 편집으로 만든 로컬 시험 브랜치 `sync/account-sequence-repair-reversal`
    (`71304e322177497fbf1d32bb3394454c9644b33c`)는 공식 동기화 결과가 아니며
    병합·push·배포 대상에서 제외한다.

## 검증 증거

- 코드 커밋: `013c189d704fb097c4e46db8af4e7ecabfc0a852`
- DB/환경: Windows 로컬 Odoo 18, PostgreSQL 테스트 DB `test_akp_254`, HTTP 포트
  `18069`, `account_kr_plus_patch` 18.0.2.5.4 업그레이드.
- 실행 명령:
  - `odoo-bin -d test_akp_254 --stop-after-init --http-port=18069 -u account_kr_plus_patch --test-enable --test-tags '/account_kr_plus_patch:TestAccountKrPlusPatch.test_refund_and_normal_moves_share_the_daily_sequence,/account_kr_plus_patch:TestAccountKrPlusPatch.test_sequence_repair_shares_numbers_between_normal_and_refund_moves'`
  - `odoo-bin -d test_akp_254 --stop-after-init --http-port=18069 -u account_kr_plus_patch --test-enable --test-tags '/account_kr_plus_patch:TestAccountKrPlusPatch.test_sequence_repair_previews_before_applying_and_only_renames'`
  - `python -m compileall -q addons_custom/account_kr_plus_patch`
  - manifest AST 파싱, XML 전체 파싱, `git diff --check`.
- 결과 및 로그/산출물:
  - 신규 정상/역분개 공통 순번 테스트 1건 통과.
  - 소급 마법사 정상/역분개 중복 탐지·재번호 테스트 1건 통과.
  - 미리보기 후 동일 모달 재연결 및 적용 테스트 1건 통과.
  - Python compileall, manifest/XML 파싱, diff check 통과.
  - 로컬 정본 동기화 후 `mirror_diff.sh` 결과 일치 1 / 드리프트 0 /
    정본 없음 0.
  - 정본·미러 모듈 트리 33개 파일 일치, 대상 전용 파일 0.
  - 미러 Python AST 21개, XML 8개, manifest 파싱과 XML 로드 순서 검사가 통과했다.
- 미실행 검증과 이유:
  - 실제 브라우저 수동 UAT와 운영 DB 검증은 수행하지 않았다.
  - 전체 모듈 스위트에는 이번 변경과 무관한 기존 실패 4건이 남아 있다: 초안 번호
    표시 기대값 1건, 보관 저널 기본 선택 1건, Bill/Refund 테스트 데이터의 필수 일자
    누락 2건. 신규·변경 대상 테스트는 별도 실행해 통과했다.

## 배포·롤백

- 모듈 업그레이드/마이그레이션: 배포 DB에서 `-u account_kr_plus_patch`가 필요하다.
  기존 전표번호 마이그레이션은 없다.
- 재기동 및 확인: 모듈 업그레이드 후 Odoo를 재기동하고, 정상 전표→역분개→정상 전표
  순서의 번호와 마법사 미리보기/적용 화면 연결을 확인한다.
- 롤백 조건/방법: 신규 전기 중 중복 번호, 잘못된 회사·일자 순번 또는 외부 연계 실패가
  확인되면 이전 모듈 코드로 되돌리고 업그레이드·재기동한다. 이미 발급된 번호는 자동으로
  되돌리지 않으며 회계 담당자 검토 후 별도 정정한다.
- 사람 승인: 로컬 코드·테스트·커밋만 승인 범위다. PR 병합, 원격 push, 운영 DB 변경,
  배포 및 재기동 승인은 받지 않았다.

## 남은 위험과 후속 작업

- 남은 위험: 외부 시스템이 정상/역분개를 별도 연속 순번으로 해석하는지 확인이 필요하다.
  소급 마법사는 잠긴 기간·해시 보호 전표를 계속 차단하므로 해당 전표는 별도 회계 절차가
  필요하다.
- 미해결/후속: 실제 브라우저 UAT, 운영 전 복제 DB에서 대상 기간 미리보기 검토,
  기존 전체 스위트 실패 4건의 별도 정리.
- PR 및 handoff 회신: 로컬 작업 `👥 최신 브랜치 정본 동기화`에 정본 HEAD
  `61188b7dea77c6d27a1c0dfe7bfb2689d535b44c`와 기능 커밋을 전달했고, 공식 미러
  커밋 `74d4677a7340fc4b8acb63558cc45e86c6ad3107` 및 `diff 0` 회신을 받았다.
  PR과 원격 push는 아직 수행하지 않는다.
