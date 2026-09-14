수신: 아스트라(Codex Spark)
발신: 개발(지휘)
상태: 요청

## 원칙 (사용자 지시, 2026-09-14)
아스트라는 Codex Spark 다. 개발이 **구체 검토 항목**을 주고, Spark 결과를 **개발이 검증**한 뒤 반영한다. Spark 는 코드를 직접 병합하지 않는다 — 발견은 근거(파일:줄·재현 조건)와 함께 제출, 패치 제안은 diff 로.

## 검토 대상 (exchange.git — 이력은 GitHub 와 무관한 격리 스냅샷)
| 항목 | 브랜치 @ SHA | 파일 |
|---|---|---|
| R134 미결 이월 후속 | `dev/r134-carryover-followup-20260914` @ `8fa51f4` | `addons/gh_vendor_settlement/models/carryover_followup.py`, `tests/test_carryover_followup.py`, `views/carryover_followup_views.xml`, `R134-CHANGE-LEDGER.md` |
| R135 교체 인지 순서·R141 | `dev/r135-injection-sequence-20260914` @ `4e88e94`(제품 `4ffb480`) | `addons/injection_planning/models/planning_run.py`(`_r135_sequence`·`_evaluate_plan`·`_assert_confirmable_plan`), `planning_config.py`, `mold.py`, `R135-CHANGE-LEDGER.md` §6 1~12 |
| R136 서버 어댑터 | `dev/r136-factory-flow-20260914` @ `b7fa70b` | `addons/cams_ops_dashboard/models/factory_flow.py`, `tests/test_factory_flow.py`, `data/r136_canonical_map.json`, `R136-CASCADE-DESIGN.md`, `R136-DATA-CONTRACT.md` |

## 검토 질문 (각각 "문제 없음" 도 근거와 함께)
R134: (1) 새 기간 대사·승인·공급사 확인을 우회하는 경로가 남아 있는가(OR 예외 금지 정정 이후). (2) withdrawn 제안이 `action_prepare`·청구 마법사·집계 어디서든 다시 잡히는 경로. (3) `_approval_lock_target` 이 withdrawn 을 거부하는데 approval mixin 의 다른 진입(reset_draft 등)에서 빠지는 곳. (4) 원 미결과 후속의 금액 부호·통화·회사 일치 검사 누락.
R135: (5) `_r135_sequence` 긴급도(strictly-earlier 만 계산)가 같은 납기 다수 작업에서 순환/기아를 만들 수 있는가. (6) `not_before` 재고 상한 지연이 `_r135_due_end` 와 충돌해 infeasible 을 잘못 판정하는 조건. (7) 확정 게이트가 `sequencing_mode_snapshot == setup_aware` 에만 걸리는 것이 legacy 실행 중 설정 변경(`settings_changed`) 과 조합될 때 구멍. (8) 업그레이드 경로: 기존 DB 는 legacy 유지·신규 설치만 setup_aware — `post_init_hook` 이 재설치/`-u` 에서 덮어쓰지 않는가.
R136: (9) 계약 v3 위반 — 퍼센트, sudo, 회사 범위 누락, restricted 노드의 제목/건수 누설(상위 합계 포함). (10) `search(limit=2000)` 스캔 부분집합으로 상태 건수를 만들고 `total` 은 정확한 점 — `truncated` 표시로 충분한가, 상태별 `search_count` 로 바꿔야 하는가. (11) 어댑터 상태 매핑이 실제 selection 값과 맞는가(`e2b39ae` 에서 정정한 것 외 누락). (12) `get_action` 이 클라이언트가 준 `filters` 를 신뢰하는 범위(domain 주입 가능성).

## 제출
- exchange 브랜치 `astra/r143-review-20260914` 의 `docs/tasks/R143-SPARK-REVIEW.md`, 항목 번호별 `판정(문제/문제없음) · 파일:줄 · 재현 조건 · 제안(diff 가능) · 심각도`. 완료 시 이 파일에 SHA 회신. 개발이 각 항목을 재현·검증해 반영/기각을 같은 파일에 적는다.
- 09 배정(운영 이식 인계서 outputs/142 갱신, 사용자 확정 대기 정책 목록)은 그대로 유효.
- 추가 정보: 사용자 지시로 R134/R135/R136 후보를 **`wilcoco/odoo-uat` main(`751b6e6`) 위 이식 브랜치**(`cand/r134-carryover-20260914` 2dde5ea·`cand/r135-sequencing-20260914` 1538fa7·`cand/r136-factory-flow-20260914` fce625c, 모듈 디렉터리 전체 교체)로 만들었다. 격리 clone 의 pre-push 훅이 exchange.git 외 push 를 막아 **GitHub 반영은 사용자 결정 대기**(bundle `work/overnight/handoff-bundles/cams-candidates-20260914.bundle` 준비됨). 서버(원도영) 전달 경로 검토 의견 있으면 함께.

수신 ACK 를 남겨 주십시오.
