# 작업: 손익계산서 보정과 에이전트 머지 체계

- 저장소: `wilcoco/odoo`
- 브랜치: `account/20260911-report-adjust`
- 기준 브랜치/커밋: `18.0 / 17e9fac0eeeb`
- 요청: 사용자 직접 요청 및 `handoff/docs/tasks/README.md`
- 담당: `서버`
- 상태: `검토 요청`

## 목적과 범위

- `account_kr_reports`를 `18.0.1.5.1`에서 `18.0.1.6.0`으로 올리고 한국식·기본 손익계산서의
  확인된 수식 및 계정 유형 결함을 멱등하게 보정한다.
- 같은 브랜치에서 에이전트 공통 작업 규칙, 코드, 마이그레이션, 테스트, 검증 결과를 하나의 머지
  요청 단위로 관리한다.
- 운영 DB 직접 수정, 운영 배포, `odoo_gh` 미러 반영은 이 브랜치의 자동 실행 범위가 아니다.

확인한 결함과 보정은 다음과 같다.

| 보고서/대상 | 확인한 결함 | 보정 |
|---|---|---|
| 손익계산서(KR) 영업이익 | `KR_GRP.balance + KR_EXP.balance` | `KR_GRP.balance - KR_EXP.balance` |
| 손익계산서(KR) 법인세비용 | 계정 `63`만 집계 | `63 + 67` |
| 기본 손익계산서 영업외수익 | `42xxxx`가 `income` | `income_other`로 1회 백필 |
| 기본 손익계산서 판관비 | `61xxxx` 감가상각비가 `expense_depreciation` | `expense`로 1회 백필 |
| 기본 손익계산서 당기순이익 | 사용자 추가 `TAX` 라인을 NEP가 반영하지 않음 | 부호에 맞춰 `TAX.balance` 차감/가산 |

## 통합 영향

- 상태 전이, 수량·재고, LOT·시리얼, 품질 승인, 납품에는 영향이 없다.
- 기존 전표·잔액·세액·기간잠금 데이터는 수정하지 않는다. 보고서 수식과 대상 계정의 표시용
  `account_type`만 보정하므로 보고서 분류·표시 금액은 달라질 수 있다.
- 수식은 공유 보고서 정의이므로 해당 보고서를 사용하는 모든 회사에 적용된다. 계정 유형 백필은
  최상위 회사별 계정에서 코드와 현재 유형이 모두 일치할 때만 `sudo()`로 수행한다.
- 이미 올바른 값이면 변경하지 않는다. 수식이 알려진 결함 값과 다른 경우에는 사용자 정의로 보고
  보존하며 경고 로그만 남긴다.

## 변경 내용

- 코드 커밋 `601a6f5b3a92`: 손익계산서(KR) 영업이익·법인세 수식 및 선택 모듈 부재 안전 처리
- 코드 커밋 `7490505beba9`: `42xxxx` 영업외수익 유형 백필
- 코드 커밋 `38d425150413`: 판관비 감가상각 유형과 기본 손익계산서 NEP/TAX 보정
- `tools/report_adjust.py`: 보정 로직을 한곳에 모으고 예상 결함 일치·멱등·사용자 정의 보존 적용
- `data/report_adjust_data.xml`: 설치·업그레이드마다 공유 보고서 수식 재확인
- `migrations/18.0.1.6.0/post-*.py`: 기존 설치 DB에서 세 보정 단계를 순서대로 1회 실행
- `tests/test_report_adjust.py`: 수식, 멱등성, 사용자 정의 보존, 계정 유형, 선택 의존성 부재 검증
- `AGENTS.md`, `CLAUDE.md`, `docs/tasks/AGENT_MERGE_WORKFLOW.md`, PR 템플릿: 이후 에이전트가
  동일한 브랜치·워크트리·작업 문서 규칙을 발견하도록 연결

## 정본·미러 대응

- 정본: 이 브랜치의 `addons_custom/account_kr_reports`
- 미러 대상: `escon-odoo/odoo_gh`의 `iatf_plugins/account_kr_reports`
- 현재는 정본 PR 검토 전이므로 미러 코드 커밋을 만들지 않았다. 정본 병합 커밋을 기준으로 미러에
  동기화하고 그 커밋을 handoff에 남긴다.
- 공통 에이전트 매뉴얼은 `odoo_gh`의 `update/agent-merge-workflow` 브랜치에도 별도로 준비되어 있다.

## 검증 증거

- 런타임: WSL `/opt/odoo`, Odoo `18.0+e-20251117`, PostgreSQL 임시 DB(각 실행 후 삭제)
- 정적 검사: 변경 Python 구문 컴파일과 XML 파싱 통과, `git diff --check` 통과
- Enterprise 구성:
  `-i l10n_kr_reports,account_kr_reports --test-enable --test-tags=/account_kr_reports:TestReportAdjust`
  실행 결과 최종 HEAD의 8개 테스트 `0 failed, 0 error(s)`
- 선택 모듈 미설치 구성:
  `-i account_kr_reports --test-enable --test-tags=/account_kr_reports:TestReportAdjust` 실행 결과
  `l10n_kr_reports` 미로드 상태에서 `0 failed, 0 error(s)`; 없는 보고서를 요구하는 테스트는 skip
- 실제 업그레이드 경로: 임시 DB의 설치 버전을 `18.0.1.5.1`로 설정한 뒤
  `-u account_kr_reports` 실행. `post-10`, `post-20`, `post-30` 세 마이그레이션 호출 확인
- 원본 대조: Odoo Enterprise `l10n_kr_reports/data/profit_loss.xml`에서 결함 수식과 계정 범위를 확인
- 미실행: 운영/복제 DB의 실제 결산 금액 대조는 하지 않았다. 운영 배포 승인 전 회계 담당자가 같은
  기간의 손익계산서(KR), 재무상태표(KR), 분개장·시산표를 대조해야 한다.

## 배포·롤백

- 정본 PR을 `18.0`에 병합하고 병합 커밋 기준으로 `odoo_gh/iatf_plugins/account_kr_reports`를
  동기화한 뒤, 승인된 배포 창에서 `-u account_kr_reports`와 재기동을 수행한다.
- `l10n_kr_reports` 또는 `account_reports`만 따로 업그레이드한 경우 표준 수식이 되돌아갈 수 있으므로
  `account_kr_reports`도 함께 업그레이드한다.
- 배포 전 DB 백업이 필요하다. 코드 revert만으로 마이그레이션이 쓴 수식·계정 유형은 되돌아가지
  않으므로, 데이터 롤백은 회계 담당 승인 아래 백업 복원 또는 변경 대상의 명시적 역보정으로 한다.
- PR 병합과 운영 배포는 별도 승인이다. 운영 실행은 handoff에 명시적인 `승인:`이 있을 때만 한다.

## 남은 위험과 후속 작업

- `42xxxx`와 `61xxxx` 계정 유형 보정은 기존 설치 DB의 버전 마이그레이션에서 1회 수행한다. 신규
  DB나 이후 계정과목 가져오기에서는 계정 유형을 별도로 확인해야 한다.
- Odoo에는 한국식 `영업외비용` 전용 계정 유형이 없어 `62xxxx`의 한국식 구분은 손익계산서(KR)를
  기준으로 확인한다.
- 기본 손익계산서에 코드 `TAX` 라인이 없거나 해석할 수 없는 엔진이면 NEP 보정을 생략한다.
- 후속: PR 검토 → 운영 전 복제 DB 금액 대조 → 승인 → 정본 병합 → 미러 동기화 → 배포 결과 회신
