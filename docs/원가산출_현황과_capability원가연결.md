# 개별 품목 원가 산출 — 현황·구조공백·연결 작업

작성: 2026-07-02. 대상: cams(사출·조립 제조원가). 상태: 현황 진단 + capability↔원가 연결 착수.

## 진단 (cams_sim3 실측)
| 항목 | 값 | 의미 |
|---|---|---|
| 원가법 | 표준(standard) + manual_periodic (전 카테고리) | 실제원가 아닌 표준단가 기반 |
| 품목 standard_price | 전부 0 | 원가 미입력 |
| 워크센터 costs_hour | 0 | 노무·설비 가동비 미반영 |
| BOM operation(공정) | 0개 | 가공비 배부 근거 없음 |

## 핵심 구조공백 (★ 잊지 말 것)
**사출 시간관리와 Odoo 표준 원가엔진이 분리돼 있음.**
- 사출 소요시간 = 커스텀 `injection.machine.mold.capability.cycle_time`(초) / cavity.
- Odoo 표준 원가 roll-up = **BOM operation(라우팅) + 워크센터 `costs_hour`** 기반.
- 둘이 안 붙어 있어 **사출 가공비가 제품원가로 자동 산출 안 됨.**

## 원가 요소별 가능성
| 요소 | Odoo 네이티브 | 현 상태 |
|---|---|---|
| 재료비 | ✅ BOM roll-up | 단가 0 → 입력 필요 |
| 가공비(노무·설비) | ✅ 공정+costs_hour | ❌ 사출시간이 capability에만 |
| 간접비(OH) | △ costs_hour에 얹어 근사 / 정교하면 분석회계 | ❌ 없음 |
| 실제 vs 표준 | ✅ average/FIFO 전환 시 | 표준이라 변동 미반영 |

## 연결 작업 (구현)
사출 가공비를 표준 원가엔진에 태우는 방법 = **capability→BOM operation 브리지**:
1. 사출부품 BOM에 공정(operation) 자동 생성 — 워크센터=capability.workcenter, 시간=capability 기반(cycle_time×cavity당 환산).
2. 워크센터 costs_hour 설정(노무+설비+간접 배부 합산 요율).
3. 제품 '원가 계산'(compute price) → 재료비+가공비 roll-up.
→ 상세/결과는 본 문서 하단 "구현 기록"에 갱신.

## 기초자료 임의 세팅 (회사 전체 가동용, cams_sim3)
- 원재료 kg단가·외주 계약단가·워크센터 시간당원가·조립 인력단가 등 대표값 입력(추후 실제값 교체).

## 구현 기록 (2026-07-02, cams_sim3 — 완료·검증)
### 세팅한 기초자료 (전부 임의 대표값, 실제값 교체 필요)
| 항목 | 값 |
|---|---|
| 워크센터 사출기-2500T costs_hour | 80,000/h |
| 워크센터 사출기-1300T costs_hour | 60,000/h |
| 워크센터 **조립라인-1(신규)** costs_hour(인력단가) | 35,000/h |
| 수지 RM-PP-RESIN standard_price | 1,200/kg (톤 120만/1000) |
| 외주 OUT-FST-C / OUT-CLP-D standard_price | 520 / 180 |

### capability↔원가 연결 (BOM 공정 생성)
사출 시간(capability.cycle_time/cavity)을 BOM operation(mrp.routing.workcenter, time_mode=manual)으로 브리지:
- INJ-SHELL-A: '사출성형' @사출기-2500T, 55초/cav1 = 0.917분/개
- INJ-BRKT-B: '사출성형' @사출기-1300T, 38초/cav2 = 0.317분/개
- FIN-BPR-A: '조립' @조립라인-1, 3분/개
- FIN-BPR-B: '조립' @조립라인-1, 2분/개

### roll-up 결과 (button_bom_cost, 재료비+가공비 검증 일치)
| 품목 | 재료비 | 가공비 | 표준원가 |
|---|---|---|---|
| INJ-SHELL-A(범퍼쉘) | 3,840 | 1,222 | **5,062** |
| INJ-BRKT-B(브라켓) | 1,320 | 317 | **1,637** |
| FIN-BPR-A(프론트범퍼ASSY) | 8,222 | 1,750 | **9,972** |
| FIN-BPR-B(리어범퍼ASSY) | 4,313 | 1,167 | **5,480** |

→ **가공비 > 0 확인 = capability→원가 연결 성공.** 이전엔 전부 0이었음.

## 코드 브리지 구현 (2026-07-03 — 완료·검증)
파일: `injection_worksite/models/machine_mold_capability_cost_bridge.py` (v18.0.2.6).
capability(`_inherit`)에 **자동 원가연결** 추가:
- **자동동기**: capability create/write(cycle_time·defect_rate·workcenter·mold·active) 시, 제품별 **대표 capability**(hourly_capacity 최대, planning best_cap와 동일기준)로 제조 BOM에 '사출성형' 공정을 upsert. unlink 시 남은 조합으로 재동기.
- **명목 표준**: 공정시간(분/개) = `cycle_time/cavity/60`. **불량률은 표준에 미반영** — 표준은 불량0 기준선. 불량은 실제 MO에서 실제 투입돼 실제원가로 잡히고 표준과의 차이(variance)로 분석(초기 수율보정판을 명목으로 정정, 2026-07-03).
- **명시적 재계산**: standard_price는 Odoo 기본대로 '원가 계산'에 위임(마스터 편집 시 원가·평가 조용히 안 바뀜). 일괄 재동기 서버액션 `action_sync_bom_operations` 제공.
- `is_cost_driver` 필드: 여러 조합 중 원가기준 조합 조회용.

검증(cams_sim3, -u): 공정삭제→액션 복원 OK / SHELL 0.9354분·BRKT 0.3231분(수율2%) / write훅 defect2→10%→1.0185분(이론치 일치) / 원가 재계산 SHELL 5,087·BRKT 1,643·FIN-A 9,997·FIN-B 5,493.

## 남은 한계 (다음 단계 — 결정 필요)
| # | 구멍 | 성격 | 조치 |
|---|---|---|---|
| 1 | ~~capability→공정 자동동기~~ | ~~코드~~ | ✅ 완료 |
| 2 | ~~불량률(defect) 설비시간~~ | ~~코드~~ | ✅ 완료 |
| 3 | **재료 수율손실**(불량샷 수지소모) | BOM qty 성격(net/gross) 결정 필요 | 3.2kg가 net면 gross-up=정답이나, **마스터 변경**이라 사용자 확인 후 |
| 4 | **initial_scrap**(교체 초기불량) | 로트크기 의존 | 단위 표준원가 아닌 **실제 MO원가**에서 반영이 정석 |
| 5 | **조립 인력단가 정밀화** | 작업자수·공수 | 현재 flat 3/2분 → employee_ids/공수 모델은 설정 |
| 6 | **간접비 별도 배부** | costs_hour에 근사 포함 | 정교화는 분석회계 |
| 7 | **실제원가 vs 표준 차이분석** | 아키텍처 | average/FIFO + real_time 전환(무발주 정산모델과 상호작용 검토 필요) |

## 적용 범위·git
- 적용 DB = **cams_sim3만**. 실 DB(cams) 반영 별도 결정.
- 코드 변경(injection_worksite v2.6)은 현재 작업트리(fix/settlement-review)에 있음 → PR은 costing 별도 브랜치로 분리할지 결정 필요.
