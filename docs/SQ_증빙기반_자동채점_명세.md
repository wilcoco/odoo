# SQ 증빙 기반 자동채점 — 구현 명세 (IATF/SQ 세션 인계용)

작성: 2026-07-02 (시뮬레이션 세션 → IATF/SQ 세션 인계). 대상 모듈: **addons_custom/sq_evaluation**.
전제: sq_evaluation은 IATF/SQ 세션의 활성 모듈이므로 **구현은 그 세션에서** 수행(동시편집 충돌 방지). 본 문서는 시뮬로 증빙 흐름을 검증한 세션이 제공하는 구현 명세.

---

## 1. 목적 / 사용자 의도
- 기존 **자가평가**(심사자가 이행상태 수기 판정 → 시스템이 점수·등급 계산)는 유지.
- **별도 메뉴로 "증빙 기반 자동채점"** 을 추가 → 시스템이 실데이터 증빙을 보고 **이행상태 제안값**을 산출.
- 의도: 자동채점 결과에서 **미흡/보완 항목을 식별해 보강**. 심사자는 제안을 검토·**확정만**.
- ⚠️ 자동값이 최종 확정을 덮어쓰지 않음 — **제안(proposed) ≠ 확정(status)** 분리 필수.

## 2. 현재 구조 (변경 없이 재사용할 것)
- `sq.evaluation`(평가서, framework=sq/iatf) → `sq.evaluation.line`(항목별, `status`=이행상태 수기, `ratio`·`effective_max`·`score` 계산).
- 이행상태 배율 `STATUS_RATIO`: 우수1.0 / 양호0.8 / 보완0.6 / 일부미흡0.5 / 다수미흡0.25 / 미흡0.0 / na(분모제외).
- `sq.evidence.mixin`: `evidence_count`(자동), `_evidence_domain()`, `_evidence_target()`(→모델), `action_view_evidence()` — **이미 존재**. 라인이 이 믹스인 상속.
- 증빙 출처 `EVIDENCE_MAP`(26종): iqc/process_inspection/msa/spc/calibration/nc/ppap/traceability/control_plan/field_record … + "none".
- `EVIDENCE_DATE_FIELD`: 출처별 기간 스코프용 날짜필드.

## 3. 추가 사항

### 3-1. 필드 (sq.evaluation.line)
| 필드 | 타입 | 용도 |
|---|---|---|
| `proposed_status` | Selection(STATUS_SELECTION) | 자동 제안 이행상태 (확정 아님) |
| `proposed_ratio` | Float (compute) | 제안 배율(참고 표시) |
| `proposed_reason` | Char | 근거 요약 (예: "합격률 98.5%(4건)") |
| `auto_scored` | Boolean | 자동채점 실행됨 표시 |

`status`(확정)는 그대로. 뷰에 proposed_* 컬럼 추가, status와 나란히 비교.

### 3-2. 자동채점 로직 — `action_auto_propose(self)` (sq.evaluation)
전 라인 순회하며 증빙출처별 규칙으로 `proposed_status` 산출:

```
for line in self.line_ids:
    src = line.evidence_source
    model, _ = line._evidence_target()      # 미설치/none → (None, ..)
    if model is None:                        # Odoo 연동 없는 항목(현장/수기)
        line.proposed_status = False; line.proposed_reason = "수기 증빙 항목(자동 대상 아님)"; continue
    recs = <_evidence_domain 으로 조회된 레코드>   # 기간 스코프 포함
    n = len(recs)
    line.proposed_status, line.proposed_reason = _rule(src, recs, n)
    line.auto_scored = True
```

### 3-3. 출처별 판정 규칙 `_rule(src, recs, n)` (품질지표 기반 — 시뮬로 검증된 값)
| 출처 | 지표 | 우수 | 양호 | 보완 | 미흡/미달 |
|---|---|---|---|---|---|
| iqc / process_inspection | 합격률 = pass/decided | ≥99% | ≥95% | 검사 有·미달 | 0건 |
| spc | 평균 Cpk | ≥1.67 | ≥1.33 | ≥1.0 | <1.0 or 0건 |
| msa | %GRR(pct_grr) | <10 | ≤30 | 있음·초과 | 0건 |
| calibration | 기한내 정상 비율 | 100% | — | 일부 초과 | 초과 有 / 0건 |
| nc | 종결율(closed/전체) | ≥90% | ≥70% | <70% | (부적합 관리 존재=양호 이상, 0건이면 "기록없음") |
| ppap / apqp / fmea / control_plan | 승인·완료 건수 | ≥1 승인 | ≥1 | 진행중만 | 0건 |
| traceability / document / training / equipment / mold / jig / environment / audit / management_review 등 (건수형) | 건수 | — | ≥1건 | — | 0건 |
| field_record | 적합률(pass/total) | ≥95% | ≥80% | <80% | 0건 |
| none | — | (자동 제외 — 수기) | | | |

- 지표 계산은 각 모델의 기존 필드 사용: iqc `quantity_inspected`/`result` · spc `cpk` · msa `pct_grr` · calibration `next_calibration_date` · nc `state` · ppap `state`/`customer_decision` 등.
- 규칙표는 상수/설정으로 빼두면 조정 용이(권장: 모듈 설정 or sq.criteria에 임계값 필드).

### 3-4. 확정 흐름 (심사자)
- `action_apply_proposal()`: **선택 라인 or 전체** 의 `status ← proposed_status` 반영 → 기존 `_compute_score`가 점수·등급 자동 재계산.
- 개별 라인은 심사자가 proposed와 다르게 최종 판정 가능(자동은 제안일 뿐).

### 3-5. 별도 메뉴 / 뷰
- 평가서 폼 헤더 버튼: `[자동채점 제안]` → `action_auto_propose` / `[제안 일괄 확정]` → `action_apply_proposal`.
- 라인 리스트: `증빙건수 | proposed_status | proposed_reason | status(확정)` 나란히.
- **미흡·보완 보강용 별도 액션/필터**: `proposed_status in (미흡,다수미흡,일부미흡,보완)` 필터 뷰 → "보강 필요 항목" 리스트(사장님 핵심 의도). 대시보드 카운트도 가능.

## 4. IATF 배점 갭 (같이 처리 권장)
- 시뮬 검증 결과 **IATF 30조항의 max_score가 전부 0** → IATF 평가는 점수/등급이 0/0.
- 선택 ①: IATF는 점수 대신 **증빙 커버리지(%)** 로 평가(등급 미사용) — 자동채점 제안은 그대로 유효.
- 선택 ②: 30조항에 조항별 배점 부여(sq_iatf_criteria_data) → SQ처럼 점수·등급 산출.
- → 자동채점 기능과 무관하게 **IATF 기준 데이터 결정 필요**.

## 5. 검증 기준 (구현 후)
- cams_sim(1·2차 시뮬 데이터 있음)에서: `[자동채점 제안]` → SPC 항목 우수(Cpk 2.09)·MSA 우수(%GRR 0.95)·검사 항목 실합격률 반영·0건 항목 미흡 제안되는지.
- proposed ≠ status 분리(자동이 확정 안 덮음), `[일괄 확정]` 후 점수·등급 재계산.
- 미흡/보완 필터에 보강대상만 뜨는지.

## 6. 참고 (시뮬 실측 — 규칙 임계 검증용)
- SPC Cpk 2.09 / MSA %GRR 0.95(acceptable) / 교정 차기일 자동 / 수입검사 합격률 33%(데이터 적음) — 모두 프로세스 계산값.
- 증빙 커버리지 현재: SQ 26/47(55%) · IATF 13/30(43%). 자동채점은 이 증빙 위에서 이행상태를 제안.
