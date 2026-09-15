# R144 사용자 시나리오 E2E — 생산 담당 관점의 회사 운영 한 바퀴 (사용자 지시 2026-09-15 01:3x KST, UAT)

> 원문(사용자, 요약 없이 단계로만 나눔). 이 문서는 UAT(`https://odoo-production-beb1.up.railway.app`, 합성 데이터) 에서 개발이 브라우저로 E2E 를 수행하는 기준이며, 테스트 세션의 결함 재현 기준이기도 하다. 결과는 §3 에 append.

## 1. 시나리오(사용자 원문 순서)
| # | 사용자 말 | 해당 모듈/화면(추정 — 실행하며 확정) |
|---|---|---|
| S1 | 원청의 기간별 생산 계획을 받아서 수행. **자료가 비어 있으니 임시로 채움** — 완성품을 아이템별·사양별·일자별 몇 개 납품 | `production_planning` 수요(`production.demand`) — 수동 입력(Oracle 연동 없음) |
| S2 | 그것으로 생산 계획을 잡음 — 생산계획 모듈 | `injection_planning` 계획 실행(run) 생성·계산 |
| S3 | 생산 계획이 최적화되었는지 로직으로 검토 | R135 setup_aware 순서·평가(`_evaluate_plan`)·위반·확정 게이트 |
| S4 | 검토 후 생산 진행 → 사출 작업장에 작업지시 | 계획 확정 → MO 생성(`mrp.production`, planning_line_id) → 사출 작업장 |
| S5 | 사출기가 생산하면 생산량이 잡힘 | `injection_worksite` 실적/양품 확정(`injection_good_source`) |
| S6 | 품질검사 | `iatf_process_inspection` 공정검사 |
| S7 | 그 과정에서 원재료(수지) 차감 | `injection_worksite` 사일로/수지 이동, BOM 소비 |
| S8 | 발주 수준이 되면 발주 → 입고 → 수분 측정 등 원재료 검사 | 수지 발주(`purchase.order`) → 입고(`stock.picking`) → `iatf_incoming_inspection`(수분) |
| S9 | 사출품이 재고로 쌓이고 조립 준비 | `stock.quant` 사출품 재고 |
| S10 | 기간 생산계획을 BOM 으로 풀어 필요한 부품 수급 → SCM 으로 업체 통보 | `supplier_portal_purchase` 외주 계획(`outsource.planning.run`) → 공급사 포털 |
| S11 | 부품 납품 → 입고 검사 → 부품 재고 등록 | `stock.picking` incoming → `iatf_incoming_inspection` → 재고 |
| S12 | 원청 BR 이 실시간으로 들어오면 그에 따라 조립. **공정이 없으면 2개 공정으로 설정** | `escon_br_intake` BR 수신 → 조립 MO/작업지시(`gh_total_mes`), 공정 2개 |
| S13 | 각 공정에서 조립 부품 이종 검사 | `mrp_bom_scan_guard` 스캔 이종검사 |
| S14 | 품질검사 → 일부 불량 확률 처리 → 납품 | 출하검사(`iatf.shipping.inspection`), 부적합(`iatf_nonconformity`), BR 도착/납품 |
| S15 | 월말에 생산량 기준으로 업체 마감 | `gh_vendor_settlement` 생산량×BOM 정산·대사·(R134) 이월 후속·청구 |

## 2. 실행 규칙
- UAT 합성 DB 에 **계획·기준 입력 데이터는 임시로 만든다**(사용자 지시). 실적은 화면 절차로만 만든다(직접 SQL·데모 로더 금지).
- 각 단계: 화면 경로 → 입력 → 기대 → 실제 → 판정(통과/결함/막힘) → 스크린샷 ID. 막히면 단계 건너뛰지 않고 "막힘" 으로 남기고 다음 단계는 가능한 범위에서.
- 결함은 테스트 세션 재현·정정 배정(큐), 정정은 격리 검증 → odoo-uat main → `railway up`.

## 3. 실행 기록 (append)
