# 메인 서버 머지 전 QA 검증 계획 (~60분)

작성: 2026-06-26. 대상: 우리가 손댄 모듈 전체. 목표: 머지 Go/No-Go 판정.

## 검증 환경
- **cams** (236모듈, IATF+사출+SCM 공존) = 통합/회귀 진실원천 (super() 충돌 등은 여기서 드러남)
- **cams_test** (깨끗, 124모듈) = 사출계획·SILO·SCM 클린 e2e

## 범위 (손댄 모듈)
injection_planning · injection_worksite(SILO·x_is_injection) · supplier_portal_purchase(SCM) ·
iatf_incoming/process/shipping_inspection · iatf_msa · iatf_approval · (인프라)Oracle연동

## 단계 (시간 배분)
| # | 단계 | 시간 | 내용 | 판정 |
|---|---|---|---|---|
| P1 | 설치/업그레이드 무결성 | 15m | 손댄 모듈 -u 클린(에러 0) | |
| P2 | 모듈별 기능 e2e | 20m | 계획확정→MO / SILO발주→입고→충전 / SCM자동발주→포탈→승인 / IATF검사+결재 | |
| P3 | 통합/회귀 | 15m | MO 생성→완료→입고 (IATF+사출 메서드충돌 super() 안전) / stock.move / 회계연계 | |
| P4 | 데이터정합·엣지·권한 | 10m | 중복발주방지·상태흐름·이중적재가드·tester 권한 | |

## 합격 기준
- P1: -u exit 0, 치명오류(Traceback/Failed to load) 0
- P2: 각 e2e 최종상태 도달(MO confirmed, SILO 충전, PO approved, 검사 approved)
- P3: MO create→done 정상(한쪽 로직 누락 0), 입고picking·매입계산서 생성
- P4: 중복발주 0, 상태전이 정상, 권한 정상

## 결과 (실행: 2026-06-26)

### P1 설치/업그레이드 무결성 — ✅ PASS
손댄 모듈 8개(injection_planning·injection_worksite·supplier_portal_purchase·iatf_incoming/process/shipping_inspection·iatf_msa·iatf_approval) cams 일괄 -u: exit 0, 치명오류 0, br.db.model(기존 무관) 외 ERROR 0.

### P2 모듈별 기능 e2e — ✅ PASS (1 finding)
- P2a 계획확정→MO: PASS (review→confirmed, MO 생성)
- P2b SILO 자동발주→입고→자동충전: PASS (LOT추적 원재료에서 100→900kg 충전)
  - ⚠️ **Finding: 사일로 원재료는 LOT 추적(tracking=lot) 필수.** tracking=none이면 입고 자동충전이 조용히 skip(크래시X, 메시지O). 운영 데이터의 SILO 원재료를 LOT추적으로 설정해야 함.
- P2c SCM 자동발주→포탈응답→승인: PASS (portal_state·response 둘 다 approved)
- P2d IATF 검사+결재: 모델 install/생성 정상이나 **결재 플로우는 feat/iatf-company-forms(다른 세션 WIP)** → 이번 머지 웨이브 대상 아님(분리).

### P3 통합/회귀 (★머지 안전 핵심) — ✅ PASS
MO 생성→확정→**완료(done)** 가 IATF+사출+SCM 전부 공존 상태에서 정상.
mrp.production 다중 create/button_mark_done override(7개 모듈) + stock.move._action_done super() 체인 안전 = 한쪽 로직 누락 없음.

### P4 데이터정합·엣지·권한 — ✅ PASS
중복발주 방지 / 이중적재 가드 / 수준상태 정합(normal/low) / tester 계정·권한 전부 PASS.

## 판정: 🟢 GO (조건부)
- **머지 대상(안정)**: injection_planning(메뉴) · injection_worksite(SILO·x_is_injection·채터) · supplier_portal_purchase(SCM수정) · Oracle연동 · deploy인프라 → **머지 가능.**
- **머지 제외(WIP)**: feat/iatf-company-forms(IATF 회사양식) → 다른 세션 진행 중, 별도 웨이브.
- **머지 전 조치 1건**: 운영 SILO 원재료를 **LOT 추적**으로 설정(P2b finding). 미설정 시 입고 자동충전 미동작(데이터 손상은 없음).
