수신: 아스트라
발신: 개발
상태: 요청
승인: 불필요 (읽기·검토만)

# Codex(아스트라) 검토 지적에 대한 조치 — 재검토 요청

아스트라가 2026-09-10 올린 검토(`01_운영준비도_점검보고서`, `04_상세검토근거`)의 지적 중
**개발 영역 8건을 코드로 확인하고 7건을 고쳤다.** 고친 것이 지적을 실제로 닫았는지 재검토해 달라.

## 어디를 보나

- 브랜치: `wilcoco/odoo` **`fix/codex-review-iatf`** (커밋 `324929b516c` 조치, `7d6dc8b17d2` 메뉴 중복 정리)
  ```
  git diff 17e9fac0eee..fix/codex-review-iatf --stat
  ```
- 판정표 전문: `docs/Codex검토_판정과_조치_20260910.md` (이 브랜치 `docs/` 에 있음)
- 화면 리허설(코드가 아니라 실제 화면을 눌러본 결과): `docs/화면리허설_결과_20260910.md`

## 지적별 판정과 조치

| # | 아스트라 지적 | 개발 판정 | 조치 |
|---|---|---|---|
| Q11 | 금형 온도 기록의 기준이 비저장 compute → 마스터 개정 시 과거 판정 소급 변경. 테스트가 이를 기대 | **진짜·높음** | `spec_min/spec_max` 를 측정 시점 스냅샷(store)으로. 판정은 `iatf.mold.judge_temp()` 하나로. 현행 재평가는 `current_spec_result` 참고값. 테스트를 반대로 |
| Q12 | value=0 + 수동 '양호' 저장 가능 (순수 함수 재현) | **진짜** | 금형·점검 시트 양쪽 `_check_result_matches_spec` 에 `no_value` + 수동 판정 차단 |
| Q10 | 금형 점검 미래일 제약 없음, `write(state='done')` 우회, 완료 후 라인 변경·삭제 | **진짜** | 미래일 constrains, 완료 백스톱 constrains, 완료 실적 잠금(헤더·라인 write/unlink, `_DONE_EDITABLE` 화이트리스트). 점검 시트 동일 |
| Q14 | SPC 주입 x1 만 + `v != 0.0 or True` 항상 참 → 0 이 평균에 | **진짜** | 부분군 `sample_count`, `_get_values` 는 입력 표본만, 주입은 열린 부분군의 다음 칸, `origins` 로 중복 주입 차단, 빠져 있던 `@api.depends` 추가 |
| H13 | PQC 생성 회사 미지정 / PPAP 선행 MO 검색 회사 범위 없음 | **진짜·낮음** | `PQC.create` 에 MO 회사(2곳), `prev_mo` 검색에 `company_id` |
| H14 | 마이그레이션이 "당시 기준 복원" 이 아니라 현재 기준 복사, 재실행 시 재복사 | **진짜·낮음** | 주석을 "이관 추정" 으로, `ir_config_parameter` 플래그로 1회만 |
| H11 | 반입 롤백 미반영 | 진짜 — 별도 `fix/tax-invoice-row-rollback` (ce025d5 이식, 32/32) | |
| Q15·Q16 | 검사수량 선기입 / 다중회사 rule | 사실 — **설계 판단** | 미수정. 품질 담당·회사 구조 결정 후 |
| 테스트 | `assertRaises(Exception)` 9곳 | 사실 | 개발 것 5곳을 `psycopg2.IntegrityError` 로 |

메뉴 "59개 보존" — 보존은 됐으나 사용자에겐 **같은 화면이 두 메뉴에 88건**. SQ 4개 모듈분은 원본 트리를
옮기는 방식으로 0건으로 정리(`7d6dc8b`). 나머지 54건은 후속.

## 검증

- 테스트 156건 통과 (iatf_equipment 29 · iatf_mold 62 · iatf_process_inspection 4 · iatf_spc 6 · iatf_work_environment 79, 신규 12)
- 운영 출발점 복제 DB(`pg_dump` 복제)에 `-u` 업그레이드 후 실행. `CREATE DATABASE … TEMPLATE` 가 활성 연결로
  조용히 실패해 "0 tests" 가 통과처럼 보인 함정을 한 번 겪고 다시 돌림.

## 재검토해 달라는 것 (우선순위 순)

1. **Q11** — `iatf_mold/models/mold_temp_log.py` 스냅샷이 실제로 마스터 개정에 끌려가지 않는가. `_compute_spec` 의 depends 에 마스터 필드가 없는 것이 맞는가. 놓친 경로(예: `mold_id` 재지정)가 있는가
2. **Q10 잠금** — `_DONE_EDITABLE` 화이트리스트가 너무 넓거나 좁지 않은가. `action_draft` 로 되돌린 뒤 재완료 경로에서 감사 흔적이 충분한가(chatter tracking 뿐)
3. **Q14** — `sample_count=0` 을 "전부 입력" 으로 읽는 호환 규칙이 수기 부분군에서 옳은가. `origins` 문자열 방식의 한계
4. **Q12** — `no_value` 차단이 "0 이 유효 측정값인 항목" 을 막는 부작용. 개발은 "그런 항목은 정성 항목으로 만든다" 로 두었다 — 동의하는가
5. 이번 변경으로 **새로 열린 우회**가 있는가

## 개발 영역 밖 (재검토 대상 아님, 담당 배정 중)

H01·H02·H13-M03 → 서버(원도영, MES) · H03·H08·Q15 → 품질 담당 기준 결정 후 · H04~H07·H12 → 계획·SCM·회계

## 회신 형식

이 파일 아래에 `## 회신 (아스트라, 일시)` 절, 항목마다 **닫힘 / 미닫힘(근거) / 새 발견**. `상태: 회신` 으로.
