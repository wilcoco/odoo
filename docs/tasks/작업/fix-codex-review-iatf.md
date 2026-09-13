# 작업 기록 — fix/codex-review-iatf

규칙 10 에 따라 작업 브랜치에 싣는 작업 내용. 큐(`handoff`)의 요청 파일은 이 문서를 가리킨다.

## 무엇을
Codex 제3자 검토(2026-09-10) 지적 중 개발 영역 6건 조치 + SQ 메뉴 중복 정리.
판정표 전문: `docs/Codex검토_판정과_조치_20260910.md` (docs/dev-handoff-20260910 이관분)

| 커밋 | 내용 |
|---|---|
| `324929b516c` | Q11 온도 기준 스냅샷 · Q12 미기입+수동판정 차단 · Q10 미래일·완료 백스톱·완료 잠금 · Q14 SPC 표본 수 · H13 회사 범위 · H14 마이그레이션 표현 |
| `7d6dc8b17d2` | SQ 4개 모듈 메뉴 중복 0건 — 모듈 원본 트리를 새 자리로 이동 |

## 검증 (코드 커밋 + DB + 명령 + 로그)
- 코드 `7d6dc8b17d2` · DB `codex2`(운영 출발점 복제) · `-u` 7모듈 + `--test-tags` 6모듈
- **0 failed, 0 error(s) of 156 tests** — 로그 요약: handoff `docs/tasks/첨부/20260910_테스트로그_codex2.txt`
- 앞선 "145건 1실패" 보고는 잘못된 브랜치로 돌린 것(개발 귀책). 정정 경위는 큐 `20260910-03_to-아스트라_from-개발_*` 회신.

## 운영 반영 시
`-u account_kr_reports,iatf_mold,iatf_work_environment,iatf_spc,iatf_process_inspection,iatf_ppap,iatf_menu` — **iatf_menu 필수**.
자세한 절차: `docs/머지배포_요청_20260910.md`
