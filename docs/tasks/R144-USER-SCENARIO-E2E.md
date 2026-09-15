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

### 2026-09-15 01:3x~01:45 KST — 회사 운영 흐름(L0→L1→L2) · S1 진입 (개발, UAT 브라우저)
- **흐름도 L0**: 8 영역 리본·건수·연결 배지 렌더 OK, 콘솔 오류 0 (ss_8142enmi6). 첫 진입 1회 빈 화면(에셋 최초 번들 지연 추정, 새로고침 후 정상).
- **L1 수주·고객**: 3 프로세스 카드. `BR 수신·납품·도착` = **모듈 없음(br.intake 미설치)** → UAT 에 `escon_br_intake` 가 설치돼 있지 않음. S12(BR 조립) 진행하려면 설치 필요(`-i`) — 사용자 확인 후.
- **L2 원청 기간계획 수요**: 하위 카탈로그(어댑터 없음 배지) + 문서 14건 목록(SIM26-FG_A/B 2026-09-27~30, 진행) OK. 수요는 비어 있지 않고 14건 존재.
- **결함 #1 (정정·재배포 완료)**: "목록 원본 열기/원본 열기" → "목록을 열 수 없습니다" — 서버 `get_action` 응답에 `views` 배열이 없어 Odoo 18 `doAction._preprocessAction` 에서 `undefined.map` TypeError(브라우저 JS 로 재현). 정정 격리 `21337bf`(시험 0/11) → odoo-uat main → Railway 배포 `905c7ed7` SUCCESS(01:42). UI catch 가 원인을 숨기는 점은 후속(오류 원문을 콘솔에 남기도록 테스트 세션 배정 예정).
- **관찰 #2 (진단 중)**: `생산 수요` 목록(action_production_demand) 진입 시 브라우저 탭 렌더러 정지(스크립트 응답 없음) 2회. 서버 오류·콘솔 오류 없음. 뷰는 list,form 표준. 새 탭으로 재시도 예정.
- **운영 메모**: 재배포마다 `start.py` 가 uat 비밀번호를 재설정해 세션이 끊김 → 재로그인 필요.

### 2026-09-15 01:50~02:05 KST — S1 원청 기간계획 입력 · S2 사출 계획 계산 (개발, UAT 브라우저)
- **관찰 #2 확정(결함)**: `생산 수요` 를 **전체 페이지 로드**로 열면(홈 화면 메뉴 클릭, 직접 URL, 로그인 리다이렉트 모두) 브라우저 탭 렌더러가 멈춤(3회 재현, 서버·콘솔 오류 없음). 같은 액션을 **웹클라이언트 안에서(doAction)** 열면 정상. 목록 뷰 arch 는 표준(list,form, 커스텀 JS 없음). 사용자 실제 경로(홈 → 생산 수요)라 **우선 결함** → 테스트 세션 재현·원인 배정. 우회: 흐름도/다른 화면에서 진입.
- **S1 통과(관찰 #3 포함)**: 생산 수요 New 폼으로 10/01 FG_A 4 생성·확정(ss_603945535). 나머지 5건(10/01 FG_B 2, 10/02 A3/B3, 10/03 A5/B2)은 같은 ORM `create`+`action_confirm` RPC 로 생성(화면과 같은 경로, 문서화). **관찰 #3**: 수량 0 인 수요가 **확정 가능**하고, 확정 상태에서 수량 수정도 허용됨 → 정책 확인 필요(수량>0 필수? 확정 후 수정 잠금?). 사용자 결정 대기.
- **S2 통과**: 계획 실행 New(PP-202609-0003, 10/01~10/03) → 저장 → 수요 로드(6건) → 계획 계산(확인 대화) → 상태 검토, 라인 2(FG_A→INJ_A 11개 large A 08:00~08:41, FG_B→INJ_B 7개 large B 08:00~08:37), 교체 2회 0.5h(mold_unconfirmed), 지연 0, 실행가능=하드 위반 없음, 계산 방식 **legacy**(기존 DB 는 legacy 유지가 설계대로 동작). 계획 위반·지표 탭에 R135 설명문·안전재고 3일 표시 OK(ss_1645kbkze).
- **관찰 #4**: 계획 번호가 `PP-202609-0003`(10월 계획인데 9월 접두) — 시퀀스가 생성일 기준. 정책 확인.
- **S3 준비**: 최적화 로직(setup_aware 순서·평가)은 설정 `sequencing_mode=legacy` 라 비활성. UAT 검증을 위해 설정을 setup_aware 로 바꿔 재계산 예정(합성 UAT 한정, 운영 기본은 legacy 유지).
- 배포: `escon_br_intake`·`cams_quality_rework`·`cams_sq_dashboard` 를 main 에 추가하고 `UAT_INSTALL_MODULES` 로 설치 재배포 진행 중(사용자 지시).

### 2026-09-15 02:0x~02:1x KST — 모듈 설치 재배포 사고·복구, 정책 ①② 확정(사용자 위임)
- **사고**: main `e80c8e2`(escon_br_intake·cams_quality_rework·cams_sq_dashboard 추가) + `UAT_INSTALL_MODULES` 3개 → 배포 `535d4b92` 가 **CRASHED**(01:57~): `cams_quality_rework` 가 `iatf_quality_precedence`(UAT 에 없음) 에 의존해 `-i` 실패 → start.py 예외 → 컨테이너 재시작 루프, health 502/000 약 2분. 원인은 개발이 의존성 확인 없이 설치 목록을 넣은 것.
- **복구**: `UAT_INSTALL_MODULES=escon_br_intake` 로 축소(재배포 `0811b1dd` SUCCESS 01:58, health 200). `escon_br_intake` 설치 확인(로그 "Module escon_br_intake loaded"). 재로그인 필요.
- 미설치 잔여: `cams_quality_rework`(deps repair·iatf_quality_precedence·iatf_incoming_inspection·gh_vendor_settlement·iatf_traceability), `cams_sq_dashboard`(deps iatf_dashboard·cams_ops_process), `iatf_quality_precedence`(deps iatf_control_plan·iatf_process_inspection·account_kr_reports·gh_total_mes·injection_worksite). 다음 설치 전 UAT 존재 여부를 모듈 목록으로 확인한 뒤 순서대로.
- **정책 확정(사용자 "정책 두개 일단 알아서 해")**: ① 수량 0 이하 수요 확정 불가, 확정/완료 수요의 수량·일자·제품 잠금(폼 readonly + write 가드, '초안으로' 되돌린 뒤 수정). ② 계획 번호 연월 = 계획 시작월(`sequence_date=plan_date_from`). 구현 `dev/r135-injection-sequence-20260914` 최신 커밋, 시험 3건 `test_r144_policies.py` — 격리 실행 중, 통과 시 main 이식·재배포.

### 2026-09-15 02:2x KST — 정책 ①② 배포
- 격리 `dev/r135-injection-sequence-20260914` @ `5697f81`(정책 3커밋: 14b190c·231aa55·5697f81), `test_r144_policies` 3/3. 회귀 `/injection_planning,/production_planning` **1 failed / 240** — `TestStockScopeNormalisesContext.test_a_strict_context_still_counts_stock_child_locations`(재고 범위, 정책 변경과 무관한 영역). 변경 전 `4e88e94` 로 같은 DB(`cams_night_r134_r136_20260914`) 재실행해 환경(모듈 구성) 문제인지 분리 중 — 결과 아래 추가.
- odoo-uat main → 정책 이식 커밋(production_planning·injection_planning 교체) 후 `UAT_UPDATE_MODULES=production_planning,injection_planning,gh_vendor_settlement,cams_ops_dashboard` 로 재배포 `56317778` SUCCESS(02:04, health 200). 재로그인 필요.
- (추가 02:05) 회귀 1건 분리 결과: 변경 전 `4e88e94` 에서도 같은 DB 에서 **동일 실패**(1 failed / 5, `TestStockScopeNormalisesContext`) → 정책 변경과 무관. R135 검증 때 DB(별도 구성)에선 통과했으므로 **DB 구성 의존**(이 DB 는 injection_worksite·gh_vendor_settlement·iatf_* 등이 함께 설치됨 — `_stock_on_hand` 를 다른 모듈이 확장하거나 창고 구성이 달라 자식 선반 재고가 0 으로 계산될 가능성). 테스트 세션에 원인 분리 배정(우선 낮음, 운영 영향 여부 판단 필요).

### 2026-09-15 02:1x~02:3x KST — S3 최적화 검토 · S4 확정(MO 생성) (개발, UAT 브라우저)
- **S3 통과**: 설정 `순서 계산 방식` legacy→**setup_aware**(UAT 합성 한정) 저장. 검토 상태 계획에 `설정 변경됨(재계산 필요)` ✓ 표시, **확정 시도 → 서버가 차단**("계산 뒤 안전재고 일수·계산 방식 설정이 바뀌었습니다… 초안으로 되돌려 재계산") — R135 게이트 정상(ss_46087r7p5). 초안으로 → 계획 계산 → 계산 당시 방식 **교체 인식**, 안전재고 기준 달력일 D+1~D+N, 라인 6(필요일별 A 3/3/5, B 2/3/2, 모두 10/01 08:00~08:41 연속), 교체 2, 지연 0, 실행 가능, 안내 조기생산 13(재고 상한 미설정이라 당김 허용), 연장 생산 경고 4건(교체 회피, 원 수요일 보존) — 설계대로(ss_4896o4rmd, ss_7187j916e).
- **관찰 #5(경미)**: `계산 안내` 문구가 "순서 계산 방식: setup_aware(계산 당시 스냅샷)" 로 **현재 설정**을 읽고, 옆 필드 `계산 당시 방식` 은 "기존"(스냅샷) — 재계산 전엔 둘이 어긋남. 문구도 스냅샷을 써야 함.
- **관찰 #6(경미)**: `MO 생성 확인` 위자드 요약이 계획 라인 수 0·총 수량 0.00·교체 0 으로 표시(실제 6·18·2). `_compute_summary` 가 위자드 기본값 적용 전에 계산되거나 planning_run_id 컨텍스트 미전달.
- **결함 #3(높음, 기능)**: 확정 → 4 MO(13개) 생성, **교체가 필요한 첫 라인 2건(10/01 A 3·B 2)은 MO 생성 실패**로 초안 잔류(계획은 확정 상태로 이동, 채터에 "생성 실패 2건(재시도 가능)"). 서버 로그 전문: "제조오더의 소요시간이 계획보다 짧습니다… 계획 종료 08:33 / 제조오더 종료 08:03" — 라인은 `changeover_in_span_hours=0.5`, 시작 08:00(교체 포함)·종료 08:33 인데 MO 종료가 생산 3분만 반영(교체 0.5h 누락). `_get_mo_vals` 는 `planning_changeover_hours=line.changeover_in_span_hours` 를 얼리고 worksite 작업지시 소요도 그 값을 더하므로, 누락 경로는 (a) MO 에 라우팅(수동 공정) 이 있어 core 소요(교체 없음)가 쓰였거나 (b) 얼린 값이 0 인 경우. 성공 MO 4건의 `planning_changeover_hours/hourly_capacity`·작업지시·BOM 공정 플래그 대조로 확정 예정(세션 만료로 대기). 확정 뒤 재시도 경로는 있으나 사용자 관점에선 "확정했는데 일부 작업지시가 없음" — 우선 결함.
- 02:15:43 `/web/session/logout` 기록 → 세션 종료(재로그인 필요). 재배포 아님.

### 2026-09-15 02:2x~02:3x KST — 결함 #3 원인 확정·정정, S5 실적 · S7 수지 차감 (개발)
- **결함 #3 원인(UAT 실측)**: BOM 에 수동 공정 "사출성형"(사이클 1분) → 계획 연결 MO 의 종료가 작업지시 소요(생산분만)로 계산되어 첫 구간의 금형 교체(0.5h)가 빠짐. UAT 의 `injection_worksite` 18.0.7.35 에는 원가 연계 자동 공정(`injection_cost_generated`) 자체가 없음(격리 branch 보다 오래된 판). 성공 MO 4건은 교체 0 이라 우연히 일치. seed 의 legacy 계획(PP-0001) 교체 라인은 `changeover_in_span_hours=0` 으로 구식 코드가 만든 것.
- **정정**(격리 `dev/r135-injection-sequence-20260914` @ `eb852ad`): `injection_planning/models/mrp_production.py` 에 `mrp.workorder._get_duration_expected` 확장 — 계획 연결 MO·작업지시 1개·사출기 일치 시 라우팅 소요에 확정 교체시간(`planning_changeover_hours`)을 더함. 시험 `TestR144ChangeoverManualRouting`(수동 공정 + 교체 2h → MO 생성·종료=계획 종료). **반증**: 정정만 되돌린 임시 커밋 `cf4591f` 에서 같은 시험 1 error(재현됨). 회귀 `/injection_planning,/production_planning` 1 failed/241 = 기존 DB 의존 1건뿐(변화 없음). → UAT 이식·재배포는 다음 체크포인트(재로그인 최소화)에서.
- **S5(표준 MO 경로) 통과**: MO WH/MO/00100(3개) Start → Produce All(시리얼 3개 생성 17260924000055~57) → 00100-001/002/003 **Done**, 양품 3.
- **S7 통과**: 수지 재고 28,854.1 → **28,844.5 kg(−9.6 = 3×3.2)** 사일로 위치 `WH/Stock/SIM26 S1 30t` 에서 차감, 사출품 INJ_A 재고 1 → 4.
- **관찰 #7**: MO 폼 `금형`·`차종` 이 비어 있음(계획 라인엔 금형 있음) — 계획→MO 금형 전달 필드 미연결(worksite 버전 차이 가능).
- **관찰 #8(정책/갭)**: 사출 실적(양품·불량·shot) 수동 입력 위자드가 **디버그 관리자 그룹 전용**(uat 사용자 접근 불가). PLC/MQTT 가 차단된 UAT 에서 현장 담당이 실적을 넣는 정규 경로가 없음 → 표준 MO Produce 로 대체. 현장 실적 입력 UI 필요 여부는 사용자 결정.

### 2026-09-15 02:4x KST — S6 공정검사 (개발, UAT 브라우저)
- MO Produce 시 시리얼별 **공정검사(IPQC)·최종검사(FQC) 가 자동 생성**됨(6건, 초안) — 통과. `PQC-2026-0186`(WH/MO/00100-003, 시리얼 …57): 검사 시작 → 합격 수량 1·외관/치수/기능/판정 결과 합격 → 판정 완료 시도 → **서버 가드 "양의 검사 수량과 실제 검사항목이 필요합니다"**(항목 없이 판정 불가 — IATF 증빙 원칙, 통과). 검사 항목 1건(외관, 측정값 양호, 합격) 추가 후 **판정 완료** 상태 이동(결재 상신·종료 가능).
- **관찰 #9(갭)**: 자동 생성 검사에 **검사 항목이 비어 있고 `관리계획서 참조` 도 비어 있음** — INJ_A 에 관리계획서(control plan)가 연결돼 있지 않아 항목이 파생되지 않음. 실제 운영에선 관리계획서 기준정보가 필요(R136 지도 `CO.QA.SYSTEM`). 현장에서 매번 수기 항목 추가는 비현실적 → 기준정보 정비 항목.
- **관찰 #10(경미)**: 폼 상단 배지가 상태 "판정 완료" 인데 "Draft" 로 표시(상태 배지 위젯이 다른 필드를 봄).
- 체크포인트: 결함 #3 정정 `eb852ad` 를 UAT main 이식·재배포 진행(재로그인 필요). 다음 단계 S8(수지 발주·입고·수분 검사), S9(재고), S10(BOM 전개·SCM), S11, S12(BR·조립 2공정), S13, S14, S15.

### 2026-09-15 03:3x~03:4x KST — 결함 #3 UAT 검증 · S8 수지 발주→입고→수분 검사→해제 (개발, UAT 브라우저)
- **결함 #3 UAT 검증 통과**: 재배포 `249bd0a3` 후 PP-202609-0003 에서 MO 생성 재시도 → 교체 라인 2건에 **WH/MO/00104(3, 교체 0.5h, 08:00~08:33)·00105(2)** 생성, 6 라인 전부 confirmed, 제조 오더 8(시리얼 분할 포함).
- **관찰 #11(경미)**: `원재료 소요/재고` 탭 — 소요 59.70, 재고 28,854.10(계산 시점 스냅샷), **부족 수량 −28,794.40**(음수=여유인데 "부족" 표기), 충족률 48,331.83%(무의미). 표기 정리 필요. 발주 수량 0 = 발주 수준 미달(정상).
- **S8 통과(표준 경로)**: 구매 발주 New → 공급사 `SIM26 공급사 resin`·SIM26-RESIN 500kg·₩1,500 → Confirm(**P00008**, `수지 발주량 정산` 플래그 자동 ✓) → Receive → 로트 필수 가드(로트 추적 품목) → 로트 `RESIN-20260915-01` 지정 → Validate(**WH/IN/00023** Done) → 재고는 **`WH/IQC 검사대기/WH/IN/00023`** 보류 위치로(자동), **수입검사 IQC-2026-0021 자동 생성**.
- IQC: 검사 시작 → 판정 입력 → 판정 완료 시 가드 3종 확인: ① "실제 검사항목 필요"(수분 함량 항목 추가: 기타·≤0.1%·0.05·합격), ② "샘플 검사에는 검토된 샘플링 기준·샘플 수량·Ac/Re 필요"(**관찰 #12**: 샘플링 기준 기준정보 없음 → 전수 검사로 전환해 진행), ③ "실제 처분 방법 지정"(입고 승인). 판정 완료 → 종료 시 "결재 승인 후에만 마감" → 결재선 결재자 필수 → **관찰 #13**: UAT 단일 계정이라 검사원=승인자(Administrator) 자기 승인이 허용됨(운영에선 2인 분리 여부 정책 확인) → 승인(Approved) → "합격 수량 이동 준비" → **WH/INT/00017**(검사대기→WH/Stock) Validate → 해제 500, `quantity_released=500`, 수지 재고 29,344.5.
- **관찰 #14**: 해제된 수지가 `WH/Stock` 에 놓임 — 사일로 위치(`WH/Stock/SIM26 S1 30t`) 반입은 worksite 의 사일로 입고 절차가 별도(현장 담당 단계). 시나리오 "수분 측정 후 사일로" 흐름은 다음 단계에서 확인.

### 2026-09-15 03:4x~03:5x KST — S10 BOM 전개·SCM 통보 · S11 부품 납품·입고검사·재고 (개발, UAT 브라우저)
- **S10 통과**: 외주 조달 계획 New(**OUT/2026/0002**, 10/01~10/03) → 수요 로드 → 계산 실행 → 기간 수요를 BOM 으로 전개해 외주 부품 3종(bracket·clip·label) 일자별 소요(12/24/6 ×3일), 현재고·안전재고 반영 발주량 34/73/17, 발주일 09/30(리드타임 1일) 산출 → **발주 생성** → PO **P00009/P00010/P00011**(협력사별, 초안) + **협력사 포털 알림 3건 "새로운 발주가 도착했습니다"**(supplier.portal.notification) = SCM 통보 → 계획 **확정**. PO 에 협력사 응답 단계(응답 대기→응답 완료→승인→납품 완료)가 있으나 포털 측 응답은 협력사 로그인 필요(UAT 에선 내부 확인만).
- **S11 통과**: P00009(bracket 34) Confirm → Receive → 로트 필수(`BRK-20260915-01`) → **WH/IN/00024** Done → 검사대기 위치 보류 + **IQC-2026-0022** 자동 생성 → 전수 검사·34/34·판정 합격·처리 입고 승인·항목 1건 → 판정 완료 시 **가드 "모든 검사 항목에 규격·실측/관찰 근거·판정 입력"**(규격·측정 방법 보완) → 결재선(Administrator) → 상신 → 승인 → 합격 수량 이동 준비(**WH/INT/00018**) → Validate → `WH/Stock` 34, `quantity_released=34`, bracket 재고 38 → 종료.
- 관찰: 이 구간 신규 결함 없음. 가드가 많아 현장 교육 항목(항목·규격·샘플링·처분·결재선 5종 필수)으로 기록.

### 2026-09-15 03:5x~04:0x KST — S12 BR 수신 → 조립 지시(공정 2개) (개발, UAT 브라우저)
- **기준정보 설정(사용자 지시 "공정이 없으면 2개 공정")**: FG_A/FG_B BOM 에 공정 1개("SIM26 부품 확인과 조립", 조립1라인 60분)만 있어 **2번째 공정 "SIM26 최종조립·이종검사"(신규 작업장 `SIM26 조립2라인`, 30분, seq 200)** 를 두 BOM 에 추가(UAT 기준정보, ORM create).
- **S12 통과**: BR 수신 원장 New → `BR-20260915-0001`(합성 출처, 수신 15:50·납기 18:00, FG_A 2개, BODYFULL SIM26-BODY-0001) 저장 → **조립 제조오더 생성** → 상태 **생산 반영**, MO **WH/MO/00106**(2개, draft) 에 작업지시 2개(조립1라인 120분·조립2라인 60분, waiting) 생성. 처분 필요 없음(이전 개정 없음).
- **관찰 #15**: `회사 운영 흐름` 액션을 **전체 페이지 로드**로 열면 첫 화면이 빈 채로 남고(웹클라이언트는 ready), 웹클라이언트 안에서 다시 열면 정상 — 관찰 #2(생산 수요 정지)와 같은 "전체 로드 경로" 계열. 테스트 배정 01 에 함께 볼 것.
- 입력 UX 메모: 폼에서 좌표 클릭·입력이 어긋나 품목 필드에 수량이 들어간 경우가 있었음(자동화 오조작, 제품 결함 아님) → ORM write 로 정정 후 진행.

### 2026-09-15 04:0x KST — S13 조립 공정 이종검사(BOM Scan Guard) (개발, UAT 브라우저)
- MO WH/MO/00106 Confirm → 작업지시 1(조립1라인) 폼 → **Scan Component** 위자드: 예상 부품 4종(INJ_A·clip·bracket·label) 표시.
- **이종 스캔 `SIM26-INJ_B` → "Not in BOM: 이 MO 에 예상되지 않음"** + 알림·로그(Scan Guard Logs) — **S13 이종검사 통과**.
- **결함 #4(중)**: 정상 부품 `SIM26-INJ_A` 첫 스캔이 **"Component already fully consumed — Over-consumed 2.00/2.00"** 로 표시. 원인: UAT 의 `mrp_bom_scan_guard` 가 구판(`move.quantity`=예약분을 소비로 읽음, Odoo 18 의미 변경). 격리 branch 엔 아스트라 20260912 지적 반영판(`_qty_done_of_move` 가 done/picked 만 계산 + 회사 범위 검색, 시험 `test_scan_gate.py` 403줄)이 있으나 **odoo-uat main 에 이식되지 않음**(모듈 drift). 조치: 격리 VM 에서 모듈 시험 실행 후 main 이식·재배포(다음 체크포인트).
- (추가 04:0x) 결함 #4 정정판(격리 `21337bf` 의 `mrp_bom_scan_guard`) 격리 VM 설치·시험: **0 failed / 16**(로그 `artifacts/r134_install_21337bf_20260915T065630Z.log`). S14 완료 후 odoo-uat main 이식·`-u` 재배포 예정.

### 2026-09-15 04:0x~04:1x KST — 클립 입고(부품 부족 해소) · S14 조립 완료 시도 → 결함 #5 (개발)
- 조립 MO WH/MO/00106 이 clip 부족(3/8)으로 `Not Available` → **P00010(clip 73) 을 서버 메서드로 처리**(button_confirm → 로트 `CLIP-20260915-01` → button_validate **WH/IN/00025** → IQC-2026-0023: action_start_inspection → 전수·73/73·판정·처분 → 항목 create → action_decide(가드 "검사원·검사 항목·실제 처분 수량 필요" 확인) → 결재선 write(approval_line_ids) → action_submit_approval → action_approve_approval → action_prepare_release → **WH/INT/00019** validate → action_close). UI 와 같은 서버 메서드이며 UI 경로는 수지·bracket 에서 이미 확인. clip 재고 76, MO 부품 `Available`.
- **결함 #5(높음)**: MO 00106 **Produce All → "Oops! Something went wrong"**. 서버 traceback: `escon_br_intake/models/br_scan_link.py:135 _br_scan_evidence_gap` → `AttributeError: 'mrp.bom.scan.guard.log' object has no attribute 'blocking'`. 원인: 내가 UAT 에 설치한 `escon_br_intake`(격리 최신판)는 `mrp_bom_scan_guard` **신판**(scan_gate: blocking/resolved 필드)을 전제하는데 UAT 의 scan guard 는 구판 — **모듈 간 버전 의존을 매니페스트가 강제하지 않아**(관찰 #16) 설치 시 걸러지지 않음. 조치: 결함 #4 정정판과 같은 `mrp_bom_scan_guard`(격리 21337bf, 시험 16/16) 를 main 이식 + `-u` 재배포 진행 중. 후속: `escon_br_intake` 매니페스트에 scan guard 버전/의존 명시(테스트 세션 배정 후보).
- (추가 04:2x) 결함 #4·#5 정정 배포: odoo-uat main 에 `mrp_bom_scan_guard`(격리 21337bf 판) 이식 → `UAT_UPDATE_MODULES` 갱신(`-u mrp_bom_scan_guard,escon_br_intake,…`) → 배포 **`e0e7f32c` SUCCESS**(health 200). 재로그인 후 UAT 재확인 예정.

### 2026-09-15 04:3x KST — 사용자 지시 "그냥 코드상으로 테스트해라" → S12~S15 코드 시험으로 전환 (개발)
- 새 시험 `escon_br_intake/tests/test_r144_two_step_assembly.py`(격리 `dev/r136-factory-flow-20260914`): BR 수신 → 조립 지시 **2공정** → 예약 상태에서 정상 스캔 = `ok`(결함 #4 회귀) → 이종 스캔 차단 로그(`blocking`)·해소 → 완료(`button_mark_done`, 결함 #5 회귀) → 출하·납품 연결·도착(2h 이내 `pass`) → 확정 양품 → 월말 정산 마법사 → 정산행 `billed`.
- 1차 실행(`fb57e7f`, DB `cams_night_r134_r136_20260914`, escon_br_intake 신규 설치): **2 failed/2 error/74** — 기존 3건은 `mrp.production.inj_bodyfull` 부재(=`injection_worksite` 미설치 환경) 때문, 내 시험 1건은 확정 양품 기록을 기존 신뢰 API(`_confirm_good_output`)로 하지 않은 시험 쪽 누락. 정정 후 `injection_worksite` 설치해 재실행 중.

### 2026-09-15 04:4x KST — S12~S15 코드 시험 **통과** (개발, 격리 VM)
- 실행 조합: `dev/r135-injection-sequence-20260914` @ **`af7430d`**(R135 injection_planning + injection_worksite 신판 + escon_br_intake + mrp_bom_scan_guard 신판 + gh_vendor_settlement — odoo-uat main 과 같은 계열), DB `cams_night_r134_r136_20260914`(injection_worksite·escon_br_intake 추가 설치).
- `TestR144TwoStepAssembly.test_two_step_assembly_scans_completes_delivers_and_settles`: **0 failed / 1** (로그 `artifacts/r134_update_af7430d_20260915T111132Z.log`). 검증 내용: BR 수신 → 조립 지시 **2공정** → 부품 예약 상태 정상 스캔 `ok`(결함 #4 회귀) → 이종 스캔 `blocking` 로그·해소 → 2공정 스캔 → `button_mark_done` 완료(결함 #5 회귀) → 출하 → 납품 연결 → 도착 기록 → 납기 판정 `pass`(2h 이내) → 확정 양품 → **R134 가드**("공급사 주장 수량 대사·내부승인·공급사 확인 완료 전 청구 불가") 확인 → 대사 작성·승인·공급사 확인 → 월말 정산 마법사 → 정산행 `billed`.
- 경로에서 발견한 것: 결함 없음(신규). 정산 가드가 정상 동작해 시험을 정상 절차로 맞춤. 앞선 실행의 3건 오류는 `injection_worksite` 미설치 환경 때문(설치 후 escon_br_intake 74건 중 0 failed).
- 전체 스위트(escon_br_intake·mrp_bom_scan_guard·gh_vendor_settlement) 합산 재실행 진행 중 — 건수 추가 예정.
- (추가 04:5x) 세 스위트 합산 재실행(`af7430d`, 로그 `artifacts/r134_update_af7430d_20260915T111206Z.log`): **0 failed, 0 error / 174** — escon_br_intake 78(R144 시험 포함)·gh_vendor_settlement 100·mrp_bom_scan_guard 18. 로그의 `duplicate key … br_intake_br_no_revision_uniq` 는 중복 BR 거부 시험이 의도적으로 내는 오류.
- **R144 종합**: S1~S11 UAT 브라우저 통과, S12~S15 코드 시험 통과. 결함 5(#1 get_action views·#3 교체 라인 MO·#4 scan guard 예약 오인·#5 escon_br_intake↔scan guard 구판 → 정정·UAT 배포 완료; #2 생산 수요 전체 로드 정지 → 테스트 배정). 관찰 #4~#16 은 정책·기준정보·표기 항목으로 사용자 판단 대기.

### 2026-09-15 05:0x KST — 관찰 #5·#6·#10·#11 코드 정정 (개발, 사용자 "진행해")
- 격리 `dev/r135-injection-sequence-20260914` @ `5a23cb3`: (#5) `_evaluate_plan` 계산 안내 문구가 `sequencing_mode_snapshot` 을 표시(재검증 시 현재 설정과 어긋나지 않음), (#6) `injection.generate.mo.wizard._compute_summary` 에 `planning_run_id`·라인 상태 의존성 추가, (#11) `injection.material.requirement` 부족 수량 `max(…,0)`·충족률 100% 상한(`is_short` 는 그대로), (#10) `iatf_approval` 결재 상태 선택 라벨 한글화(결재 초안/결재 진행/승인/반려).
- 시험: 새 시험 2건(부족/충족률·위자드 요약) + 기존 injection_planning 349·iatf_approval 24 → **0 failed**(로그 `artifacts/r134_update_77bec2d_20260915T120209Z.log`, `…5a23cb3_20260915T120441Z.log`). 참고: 이번 실행에선 앞서 DB 의존으로 실패하던 `TestStockScopeNormalisesContext` 도 통과(injection_worksite 설치 후) → 그 실패는 **injection_worksite 미설치 조합**에서만 나는 것으로 좁혀짐(테스트 배정 01 추가 정보).
- odoo-uat main 이식·`-u injection_planning,iatf_approval` 재배포 진행 중.
- (추가 05:1x) 관찰 #5·#6·#10·#11 정정 배포: odoo-uat main ← `5a23cb3` 이식(injection_planning·iatf_approval), `-u` 포함 재배포 **`5fd6c068` SUCCESS**(health 200). UAT 화면 재확인은 사용자/테스트 몫(재로그인 필요).
