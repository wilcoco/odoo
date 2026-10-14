# CAMS Odoo 전체 이해 가이드 — 큰 틀에서 세부 로직까지

작성 2026-07-07 · 목적: **표준 Odoo와 커스텀의 연계, 전체 구조, 세부 로직을 한 체계로** 파악해 향후 문제·개선을 스스로 다룰 수 있게.
읽는 법: **레이어 0~2만 읽으면 큰 틀**이 잡힙니다. 3~7은 필요할 때 내려가서 봅니다.

---

## 레이어 0 — 한 문장
> 사출·조립 자동차부품 공장을 **표준 Odoo(제조·재고·회계·구매·품질) 뼈대 위에**, 이 회사만의 규칙(무발주 생산량 정산·수지 톤정산·PLC 실측·가단가 소급·관리원가)을 **커스텀으로 얹어** 운영한다.

---

## 레이어 1 — 큰 틀: 뼈대(표준) + 살(커스텀)
```
        ┌─────────── 표준 Odoo (뼈대) ───────────┐
        │ mrp(MO·BOM·워크센터) stock(재고·로트)   │
        │ account(전표·계산서) purchase quality   │
        │ product · mail · portal                 │
        └───────────────┬─────────────────────────┘
                        │ 확장(_inherit) / 신설(_name)
        ┌───────────────┴─────────────────────────┐
        │        커스텀 (이 회사만의 규칙)          │
        │ 사출계획 · PLC실적 · SILO · 무발주정산    │
        │ 톤정산 · 관리원가 · 가/정 소급 · IATF/SQ  │
        └─────────────────────────────────────────┘
```
**핵심 원칙 3가지 (이것만 알면 구조가 보임):**
1. **커스텀은 표준을 대체하지 않는다.** 표준 모델을 `_inherit`(확장)하거나, 표준에 없는 개념을 `_name`(신설)으로 추가한다. → 표준 기능·업그레이드를 그대로 쓰면서 회사 규칙만 덧댐.
2. **표준이 "무엇을(제조·재고·회계)", 커스텀이 "이 회사는 어떻게".** 예: MO는 표준, "2단계 MO+PLC 실적"은 커스텀.
3. **회계는 표준으로 돈다.** 커스텀 정산/원가는 표준 account 위에 전표를 만들 뿐(관리원가는 회계 정본 아님).

---

## 레이어 2 — ★ 표준 ↔ 커스텀 연계 지도 (가장 중요)
### (A) 표준 모델을 커스텀이 "확장"한 것
| 표준 Odoo 모델 | 표준 역할 | 커스텀이 얹은 것 | 어느 모듈 |
|---|---|---|---|
| **mrp.production**(MO) | 제조오더 | 2단계 MO(계획/단위)·PLC 필드·양품/불량·MO완료→외주정산 생성 | injection_worksite, gh_vendor_settlement |
| **mrp.bom** | 자재명세 | (그대로) + capability가 '사출성형' 공정 자동 생성 | injection_costing 브리지 |
| **mrp.workcenter**(사출기) | 작업장 | costs_hour(가공비 요율) + capability 연결·사출 플래그 | injection_worksite |
| **mrp.workorder** | 작업지시 | 실제 가공시간 원천(능률차이) | injection_worksite |
| **stock.lot** | 로트 | 14자리 시리얼·수지 LOT 추적 | injection_worksite |
| **stock.picking** | 입출고 | SILO 자동적재 연계 | injection_worksite |
| **account.move**(전표) | 청구서/전표 | 생산량 정산·톤정산·소급이 in_invoice/in_refund 생성 | gh_vendor_settlement, gh_provisional_pricing |
| **account.move.line** | 전표 라인 | 매출 소급 낙인(prov_retro_bill_id) | gh_provisional_pricing |
| **product.template** | 제품 | is_outsourced·settle_by_ton·원가정책·허용범위 필드 | injection_worksite, injection_costing |
| **quality.check/alert** | 품질검사 | PLC 중량검사 자동생성·불량 알람 | injection_worksite |
| **purchase.order** | 발주 | 협력사 포털·소요통보 연계 | supplier_portal_purchase |
| **res.company / res.config.settings** | 회사/설정 | 원가정책(가공시간·재료수량 소스) | injection_costing |

### (B) 표준에 없어 "신설"한 커스텀 모델 (이 회사 고유 개념)
| 신설 모델 | 무엇 | 모듈 |
|---|---|---|
| injection.mold / injection.machine.mold.capability | 금형 / 사출기-금형 조합(cycle·cavity·불량률) | injection_planning |
| injection.planning.* | 사출기 배정 계획 | injection_planning |
| injection.production.record | PLC 사출 실적(1샷=1건, 실측중량) | injection_worksite |
| injection.stock.silo (+load.log) | 수지 SILO 재고·적재로그 | injection_worksite |
| material.requirement.notice | 소요예상 통보(무발주) | injection_worksite |
| material.ton.price / raw.material.settlement | 수지 톤단가 / 톤당 월정산 | injection_worksite |
| **vendor.mrp.accrual** | 외주부품 생산량 정산분(핵심) | gh_vendor_settlement |
| vendor.part.price / customer.part.price | 매입/매출 계약단가(가/정) | gh_vendor_settlement, gh_provisional_pricing |
| injection.mo.cost.actual / injection.cost.monthly.close | 실제원가(관리) MO/월 | injection_costing |
| supply.chain.* / supplier.* | 협력사 포털·SCM | supplier_portal_purchase |

> **읽는 법**: "이 기능 어디 있지?" → (A)면 표준 모델을 커스텀이 확장한 것, (B)면 커스텀 신설. 이 두 표가 코드 지도의 뼈대.

---

## 레이어 3 — 데이터 생애주기 (한 거래가 표준+커스텀을 관통)
완제품 1로트가 태어나 원가·마감·소급까지 가는 길 (☐=표준, ★=커스텀):
```
★ 사출계획(capability 배정) → ☐ 계획 MO(mrp.production) 생성
   → ★ PLC /api/plc/complete → ☐ 단위 MO 완료 + ★ 생산기록(실측중량)·☐ 품질검사
   → ★ 수지 SILO 소비(FIFO) [재고떨기]
   → ☐ 조립 MO 완료 → ★ 외주 생산량 정산분(vendor.mrp.accrual) 생성
   → ★ SILO 부족 → ★ 소요통보 → ☐ 협력사 발주/응답 → ☐ 입고
[월] → ★ 정산위저드 → ☐ 매입계산서(account.move in_invoice)   [부품]
      ★ 톤정산 → ☐ 매입계산서                                  [수지]
[원가] → ★ injection_costing: ☐표준(BOM roll-up) vs ★실제(PLC) → 차이 4분해
[소급] → ★ 정단가 확정 → ☐ 소급전표(in_invoice/refund) + ★ 표준갱신/restated
[품질] → ☐/★ IATF·SQ 증빙
```
→ 즉 **표준이 흐름의 골격(MO·전표·재고)을 담당하고, 커스텀이 분기·규칙(실측·정산·원가·소급)을 담당**.

---

## 레이어 4 — 모듈별 상세 (필요할 때 참조)
| 모듈 | 목적 | 표준 대비 | 핵심 모델·메서드 | 이번 세션 변경 |
|---|---|---|---|---|
| **injection_planning** | 사출기 배정 계획, 금형/capability 마스터 | mrp.production 확장 | injection.machine.mold.capability, planning_run._schedule | (참고: 배정 최적화 백로그) |
| **injection_worksite** | PLC 실적·SILO·품질·톤정산·정산단가 | mrp/stock/account/quality 다수 확장 | production.record, stock.silo(consume_fifo), raw.material.settlement | PLC 실측중량 수용(weight_is_measured)·생산기록 폼 편집·capability→공정 원가브리지·톤정산 멱등 |
| **injection_costing**(신규) | 실제원가(관리) 표준vs실제·차이·소급 | product/company/settings 확장 | mo.cost.actual._build_one, _price_on_date, monthly_close | ★신규 모듈 전체(이번 세션) |
| **gh_vendor_settlement** | 외주 생산량 정산→매입계산서 | mrp.production/account.move 확장 | vendor.mrp.accrual, settlement_wizard.action_create_bills | 정산 정밀·동시성·계약단가 폴백 |
| **gh_provisional_pricing**(신규) | 가/정 단가·소급·B표준갱신 | account.move.line 확장 | provisional.price.mixin._confirm_firm, _create_retro_settlement | ★신규 모듈 전체(이번 세션) |
| **supplier_portal_purchase** | 협력사 포털·SCM·소요→발주 | purchase/portal 확장 | supply.chain.*, outsource_planning_run | 포털 노출(DMZ) 설계 |
| **iatf_* / sq_evaluation** | IATF16949·자체평가 증빙 | 표준+신설 다수 | iatf.*, sq.evaluation | (다른 세션 소관) |

---

## 레이어 5 — 이번 세션에 만든/바꾼 것 (요약)
| 영역 | 산출 | 브랜치(PR) |
|---|---|---|
| 표준원가 연결 | capability→BOM 공정 원가 브리지 | feat/injection-costing |
| 실제원가(관리) | injection_costing 신규(표준vs실제·차이·커버리지·소급·정책설정) | feat/injection-actual-cost |
| PLC 실측 수용 | weight 읽기·마커·생산기록 폼 편집 | feat/plc-weight-capture |
| 가/정 소급 | gh_provisional_pricing 신규(소급전표·B표준갱신·매출마진) | feat/provisional-pricing |
| 정산 결함수정 | 동시성·권한·정밀 | fix/settlement-review |
> 각 PR은 escon-odoo/odoo_gh. 상세 로직은 docs/실제원가_관리분석_설계·가단가_정단가_설계명세 등.

---

## 레이어 6 — 향후 문제·개선 시 "어디를 보나" (네비게이션)
| 증상/요구 | 볼 곳(모델·메서드) | 관련 문서 |
|---|---|---|
| 원가가 이상 | injection.mo.cost.actual._build_one (재료/가공/차이) | 실제원가_관리분석_설계 |
| 실측중량 안 잡힘 | plc_controller.plc_complete(weight), production_record.weight_is_measured | (본 가이드 레이어4) |
| 정산 금액 오류 | vendor.mrp.accrual(cost), settlement_wizard | ERP_비즈니스로직_정리 |
| 소급 문제 | provisional_mixin._confirm_firm, vendor_part_price._create_retro_settlement | 가단가_정단가_설계명세 §8 |
| 표준원가 0/이상 | 워크센터 costs_hour, product standard_price, capability 공정 | 원가산출_현황과_capability원가연결 |
| 재고부족 통보 안됨 | stock.silo.action_create_requirement_notice, reorder_point | 운영매뉴얼 B-4 |
| 회계 반영 여부 | (레이어1 원칙3) valuation·2단계 결정 | 재무자동분개_2단계_설계·CFO검증보고서 |

---

## 레이어 7 — 스스로 확인하는 법 (의존 탈피)
**① 코드 위치 찾기**
```bash
grep -rn "_name = 'injection.mo.cost.actual'" odoo_gh addons_custom   # 모델 정의
grep -rn "_inherit = 'mrp.production'" odoo_gh                         # 표준 확장 위치
```
**② 살아있는 값 확인 (odoo shell)**
```bash
docker exec -it cams-odoo-odoo-1 python3 /mnt/odoo/odoo-bin shell -d cams_sim3 --db_password=...
>>> env['injection.mo.cost.actual'].search([])[:1].read(['total_std','total_actual'])
```
**③ 화면 ↔ 모델 연결**: 화면 우상단 디버그(개발자모드)로 model·field·action id 확인 → 코드 grep.
**④ 읽기 순서(추천)**: 본 가이드(레이어0~3) → ERP_비즈니스로직_정리 → 운영매뉴얼(상세판) → 각 설계문서(필요 영역).

---

## 부록 — 문서 지도 (학습 순서)
1. **본 가이드** — 전체 구조·표준↔커스텀(지금).
2. ERP_비즈니스로직_정리 — 업무 규칙.
3. CAMS_Odoo_운영매뉴얼(상세판) + 화면별_입력가이드 — 화면·절차.
4. 원가: 원가산출_현황과_capability원가연결 → 실제원가_관리분석_설계 → 원가시스템_회계CFO_검증보고서 → 재무자동분개_2단계_설계.
5. 소급: 가단가_정단가_설계명세.
6. 시뮬 검증: 회사운영_전체시뮬레이션_원가통합.
