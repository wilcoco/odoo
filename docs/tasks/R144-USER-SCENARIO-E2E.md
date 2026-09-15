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
