# CAMS ERP 신규 모듈 · 비즈니스 로직 종합 정리

작성: 2026-07-02. 소스 기준: odoo_gh(fix/settlement-review) + addons_custom(현행).
분석 방법: 코드 전수 판독(모듈 70개 — odoo_gh 24 + addons_custom 46). 짝 문서: `회사운영_시뮬레이션_테스트계획.md`.

## 0. 전체 구조 한눈에

```
[수요]  Oracle T_ZM_PLN / 수동 → production.demand (production_planning = 수요 허브)
   │
   ├─[사내 사출] injection_planning: BOM전개→순수요→사출기·금형 스케줄링→계획MO
   │      └─ injection_worksite(현장): 계획MO→PLC 단위MO(시리얼)→SILO FIFO 소진
   │             ├─ SILO 저재고 → material.requirement.notice(비구속 소요예상 통보)
   │             ├─ 입고 자동충전 + injection.silo.load.log(적재로그)
   │             └─ 원재료 톤당정산 raw.material.settlement × material.ton.price → 매입계산서
   │
   ├─[외주] supplier_portal_purchase: 외주계획→PO 자동생성→협력사 토큰포탈(확인/출하/이슈)
   │      └─ 납품지연 감지(has_overdue_receipt cron) → 알림 + 영향 MO 식별
   │
   ├─[조립] mrp 조립MO 완료 → gh_vendor_settlement._post_inventory
   │      └─ BOM전개 accrual(원재료 settle_by_ton 제외·단위MO 제외·계약단가 우선)
   │         → 정산위저드 → 공급사별 매입계산서
   │
   ├─[품질] 입고→IQC 자동생성(+로트 quality_hold) / WO완료→IPQC / MO완료→FQC / 출하→OQC
   │      └─ 검사 fail → iatf.nonconformity 자동생성(8D 내장) → 시정조치 → SCAR(3건룰)
   │         → iatf.supplier.evaluation 자동채점 → 협력사 등급 → PO 경고
   │      └─ sq_evaluation = 자사가 고객 SQ심사 받기 위한 자가평가(IATF 데이터를 증빙으로)
   │
   └─[경영] cams_ops_dashboard: 재고·계획·생산·SCM·품질·돈흐름 KPI 실시간 집계
```

---

# PART 1. 사출·정산·대시보드 (odoo_gh / fix/settlement-review 기준)

## 1. injection_worksite — 사출 현장 MES (v18.0.2.4)

**목적**: 사출성형 현장의 실행계층 — 2단계 MO(계획/단위), PLC 시리얼 발급·샷 완료 연동, POP 태블릿 API, SILO 원재료 관리(FIFO·자동통보·자동충전·적재로그), 원재료 톤당 월정산(매입계산서 발행).

**핵심 모델**
| 모델 | 역할 |
|---|---|
| `mrp.production` (상속) | `is_injection_mo`(계획 MO) / `is_ip_unit_mo`(단위 MO) / `parent_planning_mo_id` / `inj_serial_full` / `plc_request_id`. create·write·action_confirm·button_mark_done·action_cancel·message_post를 단위/일반 MO로 분기 오버라이드 |
| `injection.production.record` | 샷 단위 실시간 생산기록(MO·단위MO·설비·금형·시리얼 LOT·원재료 LOT·중량·QC·작업자). 생성 시 실물("1" 접두)·임시("2" 접두) 시리얼 2개 자동 발급 |
| `injection.stock.silo` (+lot.line) | SILO 마스터 + FIFO LOT 라인. 용량·재주문점·경고점·자동발주 설정 |
| `injection.silo.load.log` | **적재 이벤트 로그** — 적재 시마다 (사일로·제품·LOT·kg·공급사·load_date) 1행. 톤정산 집계 원천 |
| `material.ton.price` | 공급사×원재료 계약 톤단가(유효기간, get_price) |
| `raw.material.settlement` (+line) | 원재료 톤당 월정산 (draft→confirmed→매입계산서) |
| `material.requirement.notice` | 협력사 소요예상 통보(PO 아님 — 비구속, 납품책임은 공급사) |
| `injection.worker.log` / suspend_log / barcode.history / api.log | 작업자 로그 / 비가동(OEE 연동) / 바코드 이력 / API 호출 로그 |
| `mrp.workcenter` (상속) | `x_is_injection`, `silo_id`, `current_mold_id`, 대시보드 상태 |
| `stock.picking`·`purchase.order` (상속) | 입고 완료 시 SILO 자동충전 훅, PO의 대상 `silo_id` |
| `stock.lot`·`product.template`·`res.partner` (상속) | 사출 LOT·10자리 시리얼 / `settle_by_ton`·중량 상하한 / 사출 작업자 |

**비즈니스 규칙**
1. **2단계 MO**: 계획 MO(is_injection_mo)가 목표수량 보유, 1샷 = 단위 MO 1개(is_ip_unit_mo, qty 1, parent_planning_mo_id). 계획 MO 통계 = 생산기록 수 롤업, 양/불은 quality.check 상태 롤업.
2. **PLC 14자리 시리얼**: `'1' + 설비번호(1) + YYMMDD(6) + 일련(6)` — 설비×일자별 ir.sequence. 실물 바코드는 별도 10자리.
3. **PLC 3단계 API**(Bearer, 전 호출 api.log): ①getpcode(제품코드) → ②request(단위 MO 생성/승격+시리얼+작업지시번호+중량 상하한) → ③complete(단위 MO 완료+금형 shot수+1+SILO FIFO 소진+생산기록+중량 QC, 불합격 시 quality.alert 생성).
4. **멱등/가드**: 단위 MO 생성은 (plc_request_id, workcenter) 검색으로 재전송 중복 방지 / 초과생산 차단 / action_complete_unit_mo는 단위 MO 아니면 return / 계획 MO 완료·취소 시 미완료 단위 MO 일괄 취소 / 단위 MO는 채터 비활성(tracking_disable).
5. **SILO 재고수준**: fill% = current/capacity. empty(≤0)/low(≤재주문점)/warning(≤경고점, 기본 재주문점×1.5)/normal. FIFO 소진(consume_fifo), 적재 시 용량초과 차단.
6. **자동 소요예상통보(cron 1h)**: auto_reorder AND 잔량≤재주문점 AND 열린 통보 없음(last_notice_id 미접수 가드) → notice 생성. 수량 = reorder_qty or (용량−잔량).
7. **입고 자동충전**: picking._action_done → PO.silo_id 지정 입고만. auto_fill_on_receipt=False면 메시지만(외부 센서가 진실원천 — 이중적재 방지), True면 action_load_lots 자동 적재.
8. **적재로그**: 모든 적재마다 load.log 1행 + 해당 제품 settle_by_ton=True 자동 설정. **정산은 load_date 기준 집계**(lot line 누적수량은 월경계 부정확).
9. **톤당 정산**: action_compute(draft만) → 기간 내 load_log를 (공급사×원재료) 집계 → 톤=kg/1000 × get_price. confirm은 라인無·단가≤0 거부. **action_create_bills는 move_ids 존재 시 중복생성 차단(멱등)** → 공급사별 in_invoice(초안).
10. **POP API**: 작업자 로그인, MO start(고스트 작업자·설비 중복가동·원재료/금형 정합성 체크)/pause(OEE 손실)/resume/end, 중량측정, 불량처리, 금형교체.
11. **생산계획 위저드**: 설비→금형 제품 자동제안→준비상태(blocked: 금형·SILO·원재료 불일치 / ready) → ready만 계획 MO 생성+확정.

**연동**: injection_planning(금형 shot·capability 브리지), escon_serial(단위 MO 작업지시번호), escon_code(중량불량코드), quality_control. `settle_by_ton`은 여기서 정의·자동설정 → **gh_vendor_settlement가 소비**.

## 2. gh_vendor_settlement — 생산량 기준 협력사 정산 (v18.0.1.0.3)

**목적**: MO 완료 시 BOM 전개로 부품×공급사 accrual 적립 → 기간 정산 위저드로 공급사별 매입계산서 일괄 생성.

**핵심 모델**: `vendor.mrp.accrual`(date·MO·부품·공급사·qty·cost·amount·bill_id·state draft/billed), `vendor.part.price`(부품×공급사×회사×유효기간 계약단가), `vendor.mrp.settlement.wizard`, `mrp.production`(settlement_created + _post_inventory 훅).

**비즈니스 규칙**
1. **트리거**: `_post_inventory()` — MO 재고/원가 반영 직후 accrual 생성.
2. **가드**: BOM 없으면 스킵 / `settlement_created=True`(copy=False) 멱등 / **단위 MO(is_ip_unit_mo) 스킵**(계획 MO와 이중계상 방지) / **원재료(settle_by_ton) 스킵**(톤정산과 이중계상 방지) — 모두 `_fields.get()` 소프트 체크로 모듈 미설치에도 안전.
3. **계산**: factor = MO수량/BOM수량 → 구성품 qty = line수량×factor. 공급사 = seller_ids[:1]. 단가 = `vendor.part.price.get_price(부품,공급사,오늘,회사)` — **None(계약없음)이면 standard_price 폴백, 0.0(0원계약)은 존중**.
4. **계약단가**: 기간중복 constraint 거부. 회사 지정분 우선, 미지정은 전사공통.
5. **정산 위저드**: 기간·회사(·공급사)의 draft accrual → 공급사별 in_invoice 1건, accrual에 bill_id+billed(재정산 방지).

## 3. cams_ops_dashboard — 전사 운영 대시보드

단일 모델 `cams.ops.dashboard`(싱글턴, 전 KPI 실시간 compute). `sudo()` + **`_company_domain()` 회사필터**(멀티컴퍼니 누출 방지), 모델 부재 시 0 반환.
- 재고: 사일로 수·잔량합·저재고 수 / 사출부품(INJ)·외주부품(is_outsourced)·완제품 qty_available
- 생산계획: 진행 계획 run·계획 라인·미반영 수요 / 생산: MO 대기·진행·완료·사출 진행
- SCM: 미입고 PO·**납품지연**(has_overdue_receipt)·미접수 통보·미읽음 포탈알림
- 품질: iatf.nonconformity 미해결(레지스트리 소프트 체크)
- 돈흐름: 나간 돈(paid in_invoice)·들어온 돈(paid out_invoice)·나갈 돈/들어올 돈(residual)·미정산 accrual 합
- KPI별 드릴다운 액션 제공

## 4. injection_rawmaterial — 원재료 수분측정

수입검사용 수분측정기(XM-60/PRECISA) 데이터를 Flutter 현장앱→Bearer API로 수신(`injection.rawmaterial.moisture`). (flutter_seq,start_time) 중복방어, SILO·LOT 자동매칭. injection_worksite 의존.

## 5. 기타 odoo_gh 모듈 (요약)

| 모듈 | 요약 |
|---|---|
| escon_base_module | 기초: product 생산탭(재질/중량/사출품번), gh.tcp.client(TCP 브리지 발신로) |
| gh_total_mes | 조립/출하 MES 허브: 출하오더, MQTT(발신 TCP/수신 /plc/event), 라인상태 스택+OWL 대시보드, /wc/app 현장 컨트롤러(스캔·출하·수리), AI 내러티브(Go 게이트웨이 콜백) |
| escon_br | BR 라벨 출력(foreign table 뷰 + 프린터/콜백) |
| escon_bom_util | ALC 관리 + Excel BOM 일괄생성 + BOM 버전/diff |
| escon_bc_model / escon_car_info / escon_code | 바코드 포맷·차종 스펙 / 차종 마스터 / 코드 테이블(T_ZJ_COD)+바코드 리포트 |
| escon_mo_barcode | MO BOM/공정 바코드 리포트 |
| escon_serial | **단위 MO에만** 10자리 mo_num_seq 부여(PLC 작업지시번호 원천) |
| escon_plc_board / gh_mqtt_setup | 스키드 카운팅 PLC 보드 / MQTT 설정 UI |
| gh_transaction_statement | 거래명세서 + 이메일 토큰 승인 링크 |
| gh_stock_ex | 입고 완료 자재 → 대기 MO 자동 예약 |
| escon_accountant_dashboard / gh_fcaio / gh_update_manager / escon_manual / escon_parking / morning_rc | 회계 대시보드(JS) / 공정 AI 필드사전 / 앱 배포 / 중점관리 매뉴얼 / 주차(조회전용) / 조회(RollCall) |

---
# PART 2. 생산계획·SCM·SQ (addons_custom)

## 6. production_planning — 수요 허브
`production.demand` 단일 저장소(수요일·완제품·수량·유형 daily/hourly·소스 oracle/manual/forecast/order·상태 draft→confirmed→done). 사출계획(injection_planning)과 외주계획(supplier_portal_purchase)이 이 수요를 공유.

## 7. injection_planning — 사출 생산계획 자동화

**상태흐름**: draft → calculating → review → confirmed(MO 생성) → done / cancelled.

**핵심 규칙**
1. **수요 4경로**: 기간 내 demand 로드 / **Oracle 직접조회**(T_ZM_PLN2 일별 D00~D12 · T_ZM_PLN1 시간별 D0001R~ 피벗→언피벗, oracledb thick 모드, 품번=default_code/barcode 매칭) / CSV 임포트 / 수동.
2. **BOM 전개(_explode_bom)**: draft 수요 × BOM → 사출부품별·일자별 수요 합산(컬러 상이 완제품도 부품 단위 자연 합산). BOM 없으면 자체를 사출품으로. 전개 후 수요 confirmed.
3. **순수요(풀캐퍼 원칙)**: running_stock 롤링 — 당일 음수 방지(최우선) + 향후 N일(safety_stock_days) 실수요 확보 + 생산일은 최적 capability의 **일일 풀캐퍼** + max_inventory 초과 방지, ceil 정수.
4. **capability**: hourly_capacity = 3600/cycle_time × cavity. 복수 조합 시 최고 능력 조합의 사출기에 배정.
5. **스케줄링(금형교환 최소화)**: 사출기별 금형 그룹핑 → 전일 장착 금형(availability.last_mold_id) 그룹 최우선 → 작업량 많은 순. 금형 변경 첫 작업에만 교체시간+초기불량 부과. 계획수량 = ceil(순수요/(1-불량율))+초기불량, 최소로트 상향. 주/야 가용시간 타임라인 커서 배치. 마지막 금형을 availability에 기록해 차기 계획에 승계.
6. **MO 분할**: shift 모드 = 주/야 경계 분할(교대별 실적) / none = 작업당 1라인.
7. **MO 생성**: review→확인 위저드→라인별 mrp.production 생성(planning_run_id 링크)+confirm.
8. **원재료 소요·자동발주**: 계획 라인 BOM 재전개 → 원재료 총소요/부족/일별 롤링(결품시점) → action_create_material_po가 공급사별 PO 자동생성(date_planned = 소요일−리드타임).
9. **자동모드 cron**(기본 비활성): Oracle 조회→계획→MO까지 무인.
10. **REST API**: /api/v1/planning/{mold,capability,run} (bearer).

## 8. supplier_portal_purchase — 협력사 SCM 포탈

**핵심 규칙**
1. **토큰 공개포탈**(/supplier/*, auth=public): 토큰 검증(빈값·demo_·20자미만 거부, secrets 32byte 자동발급), PO 소유권 검증. 대시보드/PO목록·상세·응답/납품현황/공급망/협력사간 발주/재고/알림.
2. **PO portal_state**: new(자동발주+알림) → responded(협력사 응답) → approved(담당자 승인 — 확정수량·납기를 PO 라인에 반영+button_confirm) / rejected(재응답 가능) → done.
3. **supplier.order(협력사간)**: draft→sent→confirmed→shipped→received. 입고 시 연결된 tier 상태 자동 완료.
4. **supply.chain(다단계 tier)**: route/tier(누적 리드타임) → PO 생성 시 납품일 역산으로 단계별 예정일 산출+1차 자동 통지 → **출하 시 다음 tier 자동 통지 전파** → 이슈 시 담당자 알림. 헤더 = 자식 집계+진행률.
5. **알림 12종**(supplier.portal.notification): new_po/response_received/approved/rejected/production_impact/delivery_overdue/supply_chain_*/supplier_order_* — 협력사는 ir.rule로 자사분만.
6. **납품지연 감지**: has_overdue_receipt = 미완료 입고 picking의 scheduled_date < now. cron(1일)이 확정 PO 스캔 → 당일 중복 없을 때 알림+담당자 activity + **영향 MO 식별**(지연 품목을 쓰는 자재부족 MO). 미응답 리마인더 cron 별도.
7. **외주 계획 run**: 수요 로드→BOM 전개(is_outsourced 구성품)→롤링 재고(발주일=필요일−리드타임)→협력사별 PO 자동생성(+route 있으면 supply.chain 초기화).

## 9. sq_evaluation — SQ 자가평가·증빙 조회

**자사(캠스)가 HKMC 등 고객의 SQ 심사 기준에 맞는지 스스로 평가하고, 기준 항목별 증빙자료를 만들어 조회하는** 모듈. (IATF 모듈군과 함께 "기준 준수 증빙 시스템"의 한 축 — PART 3 서두 참조.)
1. 평가서 생성→기준 로드(6 카테고리 47항목, 항목별 배점)→이행상태 판정(우수1.0/양호0.8/보완0.6/일부미흡0.5/다수미흡0.25/미흡0, na 분모제외)→총점·달성률·등급(A90/B80/C70/D60/F).
2. **EVIDENCE_MAP**: 항목별 증빙을 IATF 실데이터 19종(수입·공정검사/MSA/SPC/교정/설비/금형/추적/NC/문서 등)에 매핑해 **건수 자동 카운트+드릴다운**(점수 자동화는 아님 — 판정은 수기).
3. Odoo 데이터 없는 항목은 sq.field.record(체크리스트 주기점검)로 증빙.
4. IATF에 하드의존 없음(`model in env` 소프트 체크).

## 10. 기타
- **mrp_auto_order**: 제품+수량 리스트로 MO 일괄 생성 위저드(구매 아님).
- **engel_injection**: ENGEL 사출기(Euromap63)→Go 미들웨어→Bearer API로 샷 시리얼·설비상태 수집. 시리얼 생성 시 iatf.mold 샷+1(90% 경고)·iatf.traceability 자동·SPC(중량) 자동투입. IATF 5모듈 하드의존.
- **mrp_bom_scan_guard**: WO 부품스캔 BOM 대조(오투입 방지, bus 실시간 경고+로그).
- **barcode_scanner_widget / account_menu_extend / cams_branding**: 카메라 스캔 위젯 / 회계 메뉴 확장 / 브랜딩.

---
# PART 3. IATF 16949 품질 모듈군 (iatf_* 36개)

> **본질(대표 정의)**: IATF도 SQ도 — **우리 회사가 해당 기준(IATF 16949 / 고객 SQ 심사기준)에 맞게 운영되는지를 평가하고, 그 평가 기준에 대응하는 증빙자료를 Odoo 안에서 생성·축적·조회하는 시스템**이다. 아래 검사·부적합·시정조치·SPC·교정·추적성 등 모든 운영기록이 곧 심사 증빙이며, 협력사 평가/SCAR도 "기준이 요구하는 협력사 관리"의 증빙 항목이다. 목표 = 심사 때 "기준 항목 → 증빙 기록"을 바로 꺼내 보여주는 준비 상태 유지.

공통: 대장/기록 모델은 `iatf.approval.mixin`(iatf_approval) 상속 — 업무 state + 별도 결재 approval_state. 외부 참조는 `env.get()` 소프트 참조(미설치 시 무동작). 승인 후 본문 수정 시 결재 자동 리셋.

## A. 검사 (incoming/process/shipping/layout)
- 공통 상태: draft → inspecting → decided(판정 pass/conditional/fail) → closed.
- **자동 생성 지점**: 입고 validate→**IQC 자동생성+로트 quality_hold**(보류 로트 MO 투입 차단) / WO 완료→IPQC / MO 완료→FQC / 출하 validate→OQC(**미판정·불합격 시 출하 차단**). 이전 공정 IPQC 불합격 시 다음 공정 시작 차단(품질 게이트).
- **불합격 시**: `_auto_create_nc()` → iatf.nonconformity 자동생성(IQC=supplier+협력사 / 공정=process+**production_id(MO)** / 출하=internal) + 로트 자동 격리. IQC 합격 시 보류 해제. 공정검사 판정값은 SPC 스터디에 자동 투입.
- 검사기준: iatf.inspection.criteria(제품·업체별), AQL 샘플링, 관리계획서에서 검사항목 자동 로딩, 초/중/종물 단계.

## B. 부적합·시정조치 (nonconformity, customer_complaint)
- **NC = 8D 내장**: D1팀→D2문제→D3봉쇄→D4근본원인(5why/fishbone/fta)→D5/6시정조치→D7예방→D8종결.
- 상태: draft→containment→analysis(D3필수)→corrective(D4필수)→verification(CA 1건 이상)→closed(전 CA verified 필수). CA: open→in_progress→implemented→verified(효과성 필수)→closed.
- **자동 로직**: NC create 시 ①동일 업체 6개월 3건↑ → **iatf.scar 자동 발행** ②리스크 재평가 activity. cron: 30/60일 미종결 경고. COPQ 비용은 회계전표 전기 가능.
- 고객불만: 격리 진입 시 NC(customer) 자동생성·연결, 연결 NC 미종결 시 불만 종결 차단(폐쇄루프), 로트 기반 출하 역추적.

## C. 협력사 품질 SQ (supplier_quality, outsource)
- **iatf.supplier.evaluation**: 품질40/납기25/비용15/대응력10/QMS10 → A(≥90)/B/C/D. **action_auto_score()가 실데이터 자동채점**(IQC PPM→품질, 입고 정시율→납기, SCAR 건당 -15). 분기 cron.
- 등급→`res.partner.iatf_supplier_grade` 자동 → **PO 발주 시 C/D 등급 경고 팝업**(차단 아님).
- iatf.scar: draft→issued→response→verification→closed. 외주(iatf.outsource.order) 입고 시 IQC 자동생성으로 A 파이프라인 합류.
- ⚠️ **sq_evaluation과 별개**: sq_evaluation은 자사 수감용(PART 2 §9). 수입검사 불합격→sq_evaluation 점수 자동 반영은 **없음**(증빙 건수만).

## D. 측정·시험 (msa, spc, calibration, coating_test)
- MSA: AIAG 평균-범위법 GRR(%GRR <10/≤30/>30), 1년 미재수행 알림 cron.
- SPC: X̄-R 관리한계+Cp/Cpk(≥1.33), **OOC>0 → NC(process) 자동생성**. 데이터 유입 = 공정검사 자동투입 + engel_injection 중량 자동투입.
- 교정: 자체 장비대장(iatf.measurement.equipment) — 교정기록 생성 시 상태 자동갱신(fail→quarantine), 초과·임박 알림 cron.
- 도장시험(신뢰성/부착/색차ΔE/도막두께): 판정 수동, NC 자동링크 없음.

## E. 제품승인·설계 (ppap, apqp, fmea, control_plan, drawing)
- PPAP: 18요소 버튼 생성, level 1~5, **제품 첫 MO 생성 시 PPAP 자동 생성·연결**(미승인 차단은 없음).
- APQP: 5 phase 템플릿, phase별 산출물, 자동 전개(PFMEA/CP/PPAP 분기) 존재하나 제한적. 게이트(go/no_go) 필드만.
- FMEA: RPN=S×O×D, 고위험 시 관리계획서 알림+activity.
- 관리계획서: bom_id 자동 채움, **MO 생성 시 approved CP 자동 연결**(차단 없음). 워크센터 매칭은 문자열 ilike(느슨).
- 도면관리: EO/불출대장/4M+E 대장 — mrp와 직접 링크 없음.

## F. 설비·금형·지그 (equipment, mold, jig)
- 설비: PM 스케줄(완료 시 차기 재계산), 고장(open→repairing→closed) — **수리 시작 시 비상계획(contingency) 자동 발동**. maintenance.equipment 양방향 브리지. PM 초과 알림 cron.
- 금형: 샷수명(보증/현재/PM주기) — **MO 완료 시 qty_produced만큼 타수 자동 누적, 90% 경고**.
- 지그: 일상점검/정도검증 기록. NC 자동링크 없음(3모듈 공통).

## G. 운영시스템 (13모듈 요약)
문서관리(개정 시 CR 자동)·교육훈련(MO 완료 시 역량갭 경고)·내부심사(**major/minor finding → NC 자동**)·경영검토(180일 자동집계)·리스크·품질목표(KPI 자동산출 cron)·CSR(수주 경고)·**4M변경(미승인 CR 존재 시 BOM 수정 차단 + BOM 변경 시 CR 자동생성)**·비상계획·작업환경·포장사양·고객자산·**추적성(로트 이동마다 자동 기록 + 리콜 시뮬레이션 전방/후방 추적)**.

## H. 연동 허브 (quality_bridge, approval, menu, dashboard)
- **quality.alert ↔ NC 브리지**: 양방향 **수동 버튼**(action_promote_to_nonconformity / action_create_quality_alert). ⚠️ **자동 생성 아님**, 승격 시 production_id 미복사(수동 보완 필요).
- 결재: 순차 결재선+mail.activity, 승인 후 수정 시 자동 리셋.
- iatf_menu(9 카테고리 재배치), iatf_dashboard(20여 KPI 소프트 집계+엑셀 일괄등록).

## 품질이슈 → IATF 진입 경로 총정리 (시뮬레이션 기준)
| 경로 | 트리거 | MO 링크 |
|---|---|---|
| **주경로(자동)** | WO/MO 완료→IPQC/FQC 자동생성→fail 판정→NC 자동 | **자동**(production_id) |
| SPC 관리이탈 | OOC>0 → NC 자동 | 없음(product만) |
| 현장 quality.alert | **수동 승격** 버튼 | **미복사** |
| 고객불만 | 격리 진입 시 NC 자동 | 없음 |
| 심사 지적 | finding 생성 시 NC 자동 | 없음 |

## 협력사 품질 흐름 총정리
입고 → IQC 자동+quality_hold → fail → NC(supplier) 자동 → 6개월 3건↑ SCAR 자동 → 분기 자동채점(supplier.evaluation) → partner 등급 → PO 경고. **sq_evaluation으로 자동 반영 없음**.

## 부록: 코드에서 확인된 결함/미구현 (시뮬·후속 개발 참고)
1. quality.alert→NC 자동생성 없음(수동 승격만), 승격 시 production_id 미복사.
2. supplier.evaluation.action_auto_score가 iatf.scar의 없는 필드(due_date→실제 response_due_date)·없는 상태("verified") 참조 — 미결 SCAR 존재 시 오류 가능.
3. iatf_equipment가 없는 모델 iatf.breakdown 참조(실제 iatf.equipment.breakdown) — maintenance 화면 고장 카운트 항상 0.
4. iatf_packaging이 없는 상태 'approved'로 검색(실제 active) — 출하 포장사양 경고 미발동.
5. PPAP·CP 모두 MO 차단 없음(자동 생성/연결만), APQP 게이트 필드만 존재.
6. CP↔워크센터 연결이 문자열 매칭(느슨).
