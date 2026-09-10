# 2차 재검토 — SPC / PQC·PPAP 회사 귀속 / 관련 검사 게이트

검토 원본: `quality/` = `wilcoco/odoo` `fix/codex-review-iatf` @ `7d6dc8b17d2436ccad9dfd315da7615dcbd30a0a`. 대조: `baseline/` = `18.0` @ `17e9fac0eeeb7564e72e826caaf1865ba3b466a1`. 두 디렉터리는 고정 스냅샷이며 이 검토에서 원본을 수정하지 않았다. 아래 경로·라인은 별도 표기 없으면 **quality/addons_custom/** 기준이다. 원 지적은 `outputs/04_상세검토근거.md` Q14·Q15·Q16과 H13 보완표, `work/review/quality.md`에 대응한다. `quality/addons_custom/CLAUDE.md`를 확인했다.

## 판정 요약

| 항목 | 판정 | 근거·범위 |
|---|---|---|
| Q14: 신규 자동 SPC의 미입력 0 혼입 | **부분해결** | count=1을 명시해 x1만 통계에 쓰고 n개까지 누적하는 정상 경로는 개선. 출처 ID 접두어 충돌, 수기 보완 무시·덮어쓰기, 미완성 부분군의 연구 계산 포함, 기존 데이터 복구는 남음 |
| Q14 하위: 실제 측정값 0 보존 | **해결(소스·실제 ORM 재현)** | `"0"`은 float 0.0으로 파싱되고 count=1에서 `[0.0]` 유지. 0을 빈칸으로 제거하지 않음 |
| Q14 하위: sample_count=0 수기 호환 | **해결(정의한 호환 동작)** | 0을 'n개 입력됨'으로 해석. 실제 5개 완성 수기 입력의 평균/범위 보존. 단순히 0값을 버리는 수정은 아님 |
| Q14 하위: 재계산 의존성 | **해결(소스·실제 ORM 재현)** | x1~x10, sample_count, study_id.subgroup_size를 depends에 포함. 실제 ORM에서 x1/count/study-n 변경 시 저장 계산값 갱신 확인 |
| H13: PQC 자동 회사 귀속 | **부분해결** | 단위 MO 초물 생성 분기에 company_id 추가. 일반 MO(회사5) FQC가 활성회사1에 생성되는 결함을 실제 ORM 확인. WO IPQC·OQC도 코드상 미지정 유지 |
| H13: PPAP prev_mo 회사 범위 | **해결(소스·실제 ORM, 대상 결함)** | 같은 공유품의 회사1 선행 MO가 있어도 회사6 최초 MO에 회사6 PPAP 생성 확인. 요청 검색/생성의 회사 범위 유지 |
| Q15: 자동 검사수량 전량 선기입 | **미해결(개발이 설계결정으로 유지한 범위)** | quantity_produced와 quantity_inspected에 같은 생산량 입력/누적. 사용자 실제 실측량과 분리되지 않음 |
| Q16: IATF 다중회사 record rule | **미해결(개발이 설계결정으로 유지한 범위)** | 세 모듈 보안 XML/ACL에 회사 record rule 신설 없음. 일부 자동 생성 회사 지정과 조회·편집 격리는 다른 문제 |
| Q02~Q06·Q08·Q09 관련 검사 게이트 | **미해결(이 패치의 미수정 범위)** | 출하/WO 게이트 파일은 baseline과 동일. 본 패치가 게이트를 강화했다는 근거 없음. 게이트 자체의 새 우회 변경은 확인되지 않았음 |

## 1. Q14에서 해결된 동작과 남은 결함

### 정상적인 신규 자동 주입은 개선됐다

Before: `baseline/.../iatf_process_inspection/models/process_inspection.py:177`의 루프는 라인마다 x1만 넣은 새 부분군을 만들었다. `baseline/.../iatf_spc/models/spc_subgroup.py:35`의 `_get_values`는 n개 float를 무조건 포함하므로 n=5/x1=10은 `[10,0,0,0,0]`, 평균 2/범위 10이었다.

After: `iatf_process_inspection/models/process_inspection.py:182`에서 n을 구하고 `:185`에서 0<count<n인 가장 뒤 부분군에 `x<count+1>`를 기록한다. 신규 부분군은 `:193`에서 sample_count=1/origins를 명시한다. `iatf_spc/models/spc_subgroup.py:51`~`:56`은 명시 count만큼만 값을 반환한다. x1=10/count=1은 평균 10/범위 0으로 개선된다.

AST 원 함수 모의재현에서 n=5, 6개 값 `[0,10,12,8,20,30]`을 같은 순서로 주입하면 baseline은 6부분군 → 재판정 12부분군, 수정본은 `[0,10,12,8,20]`와 `[30]`의 2부분군 → 같은 판정 재시도 후 2부분군 유지. 이 순차·동일입력의 멱등 경로는 확인했다. 실제 0도 첫 부분군 안에 보존된다. 신규 테스트 `iatf_spc/tests/test_subgroup_stats.py:21`, `:26`, `:34`, `:41`은 각각 1개 표본, 부분 채움, 수기 완성군 0 보존, count 변경 재계산을 검사한다.

### [P2 신규] 출처를 부분문자열로 비교해 서로 다른 검사라인의 실측을 누락한다

- 정확한 위치: `iatf_process_inspection/models/process_inspection.py:177`~`:181`, 특히 `if any(origin in (sg.origins or "") ...)`.
- 재현 입력: 같은 검사 id=7에 line id=1 측정값 빈칸, line id=12 측정값 `"10"`을 두고 판정한다. 부분군 origins는 `pqc:7:12`, count=1. 이후 미입력 line 1에 `"20"`을 입력하고 재판정한다.
- 실제 원 함수 모의결과: `pqc:7:1 in pqc:7:12`가 True여서 아직 주입하지 않은 line 1을 이미 처리된 것으로 건너뛴다. 부분군은 여전히 `[10]`/count=1이고 20이 누락된다. 같은 검사에 뒤늦게 측정값을 채우는 정상 흐름에서 가능하다. 숫자 ID는 특정 수치에만 국한되지 않으며 23/230 등 접두어 관계에서 발생한다.
- Before에는 중복 주입 문제가 있었지만 서로 다른 출처를 이 비교로 누락하는 분기는 없었다. 정확한 토큰 경계 비교 또는 출처 관계의 유일성 제약으로 구분해야 한다.
- 실제 ORM 추가 검증: 검사 id=2/라인1·12를 실제 생성하고 `action_decide()`를 두 번 실행했다. line1에20이 저장됐지만 subgroup id6/origins=`pqc:2:12`/count1/값`[10.0]`이 그대로여서 실제 Odoo에서도 누락을 확인했다. 근거 `isolated_orm_probes.log:140` 및 `spc_orm_results.json`의 `origin_prefix_collision`(`confirmed_bug=true`).
- 후속 확인: 두 동시 트랜잭션의 중복·경합은 이 순차 모의재현으로 확인하지 않았다. 현재 read→append/write 사이에 명시 잠금/출처 unique 제약이 없어 DB 격리·재시도 포함 검증이 필요하다. 이를 실제 동시 덮어쓰기 재현으로 단정하지 않는다.

### [P2 신규] 자동 부분군을 화면에서 수기 보완하면 측정이 통계에서 빠지고 다음 주입으로 덮인다

- 정확한 위치: `iatf_spc/models/spc_subgroup.py:52`~`:56`; `iatf_process_inspection/models/process_inspection.py:185`~`:190`; `iatf_spc/views/spc_study_views.xml:110`~`:130`.
- 재현 입력: PQC 값 10 자동 주입 → count=1/x1=10 생성. SPC 편집 목록에서 x2=12,x3=8,x4=11,x5=9를 입력한다. 이 목록은 x1~x10을 수정할 수 있지만 sample_count/origins가 없으며 write가 count를 추론하거나 갱신하지 않는다.
- 실제 원 함수 모의결과: 저장된 x1~x5는 `[10,12,8,11,9]`이나 `_get_values()`는 `[10]`, 평균10/범위0이다(입력 5개 범위는4). 다음 PQC 값99가 들어오면 '열린 부분군'으로 선택되어 x2의12가99로 덮인다. count=2/통계값 `[10,99]`가 된다.
- 실제 ORM 추가 검증: `action_decide()`로 만든 subgroup id7에 x2~x5를 write한 후 통계는 `[10]`/평균10/범위0, 다음 검사의99 주입 후 x2=99/평균54.5/범위89를 확인했다. 근거 `isolated_orm_probes.log:186` 및 JSON `manual_fill_after_auto`(`confirmed_bug=true`). 브라우저 클릭 재현은 아니며 현재 뷰가 수정하는 같은 필드의 실제 ORM write이다.
- 영향: 동일 화면에 보이는 수기 측정값이 계산에서 제외되고, 그 값을 후속 자동 주입이 변경한다. 자동·수기 혼용 정책을 정해 완성·표본수 변경 경로를 제공하거나 입력을 잠그는 보정이 필요하다. 평균이 우연히 같아도 범위와 원 측정값 유실은 남는다.

### [미해결] 미완성 부분군을 완성된 n개 군과 함께 연구 계산한다

- 정확한 위치: `iatf_spc/models/spc_study.py:122`~`:127`은 검증 없이 분석 완료 처리. `:137`~`:158`은 모든 부분군의 mean/range를 같은 가중치로 평균하고 관리도 상수를 연구의 n 하나로 선택. `:171`~`:183`의 능력 계산도 부분군 완성 여부를 확인하지 않는다.
- 재현 입력: n=5, 완성군 `[10,12,8,10,10]`(count5) + 다음 미완성군 `[20]`(count1). 원 함수 실행은 grand_mean=15, mean_range=2, UCL=16.154, LCL=13.846을 출력한다. 완성군만의 값은 평균10/범위4이다. 단일 실측을 n=5 군과 동일한 '한 군'으로 평가한다.
- 실제 ORM 추가 검증: 동일 5+1표본 구성에서 `action_calculate()`가 state=`analyzed`, grand_mean15, mean_range2, UCL16.154/LCL13.846으로 완료되는 것을 확인했다. 근거 `isolated_orm_probes.log:229` 및 JSON `incomplete_group_analysis`(`confirmed_bug=true`).
- 영향: 앞선 0 혼입 제거만으로 부분군 완성 기준·분석 유효성이 해결되지는 않는다. 수집 중 군을 분석에서 제외/차단하거나 실제 표본수에 맞는 지원 모델로 처리할 필요가 있다. 코드의 chart_type=imr 등의 선택에 맞춘 계산 분기도 이 패치에서 추가되지 않았다. 원 Q14 권고의 '부분군 완성 기준·n=1 구분'은 남는다.

### 호환·과거 데이터·재판정의 경계

`iatf_spc/models/spc_subgroup.py:28`~`:34`는 sample_count=0을 n개 완성군으로 보는 **명시적 호환 규약**이다. 실제 수기군 `[0,2,4,0,4]`은 수정 전후 평균2/범위4로 같다. 이를 수정 실패로 세지 않는다. 반면 x1=10만 있던 **기존 자동 생성군**에 count가0이면 여전히 평균2/범위10이다. 미입력 수기군도 all-zero 측정군과 구분할 수 없다. 해당 모듈 diff에는 기존 잘못된 군을 식별·정리하는 migration이 없다. 원천 증빙으로 대사한 복구 범위를 별도로 정해야 한다.

신규 `sample_count`에 허용범위 constraint가 없으므로 count=11/음수는 `:52` 조건에 걸리지 않아 다시 n개 전체로 처리된다. 연구 n도 1~10 범위를 강제하지 않는다. 이 범위 밖 입력은 추가 유효성 검증 대상이다.

동일 출처의 measured_value를 10→25로 고쳐 재판정하면 수정본은 originkey 중복으로 새 값을 건너뛰고 SPC 원값10을 유지한다(`process_inspection.py:180`). 원 Q14에 포함된 정정 절차는 구현되지 않았다. 이전 코드는 새 군을 중복으로 만들었으므로 기존 정정 설계도 적절하지 않았다. 같은 판정의 반복 클릭 방지와 승인된 측정 정정을 구분해야 한다.

`@api.depends`는 `iatf_spc/models/spc_subgroup.py:58`~`:59`에 x1~x10/count/study size까지 추가돼 재계산 선언 누락은 수정됐다. 신규 테스트는 count 및 x3 write를 확인하지만 study size 변경·부분군의 연구 분석 재수행·UI 수기혼용·출처충돌을 검사하지 않는다.

## 2. H13 PQC 회사는 단위 MO 분기만 수정됐다

- Before: `_create_pqc_inspection`의 두 create 분기 모두 회사 미지정, PQC 모델의 company_id 기본값은 `iatf_process_inspection/models/process_inspection.py:127`의 env.company.
- After 해결: `iatf_process_inspection/models/mrp_production.py:57`~`:69` 단위 MO/생산런 첫 초물 생성에 `company_id=self.company_id.id`가 추가됐다. 이 신규 record의 회사 값은 해당 단위 MO 회사로 지정된다.
- After 잔존: 같은 메서드의 **일반 MO FQC** `:73`~`:82`에는 회사가 없다. 활성 A회사+허용 B회사 MO에서 이 helper를 호출하면 공급 vals에 company_id가 없어 PQC는 기본 활성회사에 의존한다. 원 함수 모의실행으로 B(2) MO/활성 A(1)에서 단위 경로 create vals는2, 일반 경로는 미지정인 점을 확인했다. 후속 실제 ORM에서는 활성회사1에서 회사5 MO의 helper를 호출해 **company_id=1인 final 검사**가 생성됨을 확인했다(`isolated_orm_followup.log:47`, `spc_company_orm_followup_results.json`의 `normal_mo_company`, `confirmed_bug=true`). 정상 회사5 창고/제조 picking type33/sequence76을 갖춘 MO로 재현했으므로 앞선 테스트 fixture 누락과 구분된다. 단위 MO는 이 격리 DB에 MES addon이 없어 소스·AST 검증 범위다.
- 인접 미수정: WO IPQC `models/mrp_workorder.py:48`~`:59`, OQC `models/stock_picking.py:44`~`:52`도 company_id/with_company가 없다. H13 자동생성 전체를 해결한 것으로 표시하면 안 된다.
- 기존 오귀속 기록: 단위 생성의 기존 검색 `mrp_production.py:45`~`:55`가 회사 없이 production/day/shift로 기존 기록을 찾는다. 기존 오귀속 기록을 새 코드가 재회사 지정하거나 분리하지 않는다.
- 권한·격리와 구분: 자동 create vals 회사 지정은 record rule 도입이 아니다. `iatf_process_inspection/security`의 수정도 없고 해당 모델에는 `_check_company_auto`/관계 필드의 `check_company` 추가도 없다.
- 시험 범위: 기존 `iatf_process_inspection/tests/test_pqc_aggregation.py:10`은 일반 MO FQC 수/단계만 확인. `:20` 단위 집계는 worksite 필드 부재 시 skip(`:23`). 다른 활성회사·동시 집계·정정/승인후 누적·표본 실제수량은 검사하지 않는다.

## 3. PPAP prev_mo 회사 필터는 대상 결함을 해결한다

Before: `baseline/.../iatf_ppap/models/mrp_production.py:24`의 선행 MO 검색은 product/id만 비교해 타사 동일 공유품 MO가 있으면 첫 요청을 생략할 수 있었다.

After: `iatf_ppap/models/mrp_production.py:26`~`:30`에 `("company_id", "=", self.company_id.id)` 추가. `:39`의 `sudo().with_company(self.company_id)`와 `:41`~`:53` 회사 필터/명시 create는 그대로 유지된다. A회사에서 공유품의 선행 MO가 있어도 B회사 최초 MO의 **prev_mo 검색조건에서 A가 제외됨**은 원 함수 AST로 확인했다. 같은 회사에 선행 MO가 있을 때 생략한다는 기존 정책을 바꾸지 않았다.

후속 실제 ORM에서 같은 공유품에 회사1의 MO를 먼저 만들고 회사6의 첫 MO를 생성했다. 각각 PPAP id4(회사1), id5(회사6)가 생성되고 B MO에 회사6 PPAP가 연결됐다. `isolated_orm_followup.log:62`, `spc_company_orm_followup_results.json`의 `ppap_prev_mo_company`에서 `confirmed_fixed=true`를 확인했다. 이 회사필터 결함은 소스뿐 아니라 실제 생성 hook에서도 해소됐다.

본 수정은 PPAP 승인 전 양산 강제 차단, 최초 MO 동시 생성, 취소 MO 포함 여부, 배치 최초 MO 생성의 상호 조회, 기존 PPAP에 신규 MO를 연결하는 정책을 구현하지 않는다. 이것들은 이 한 회사필터 결함과 분리한 기존 범위/추가 시험 사항이다. 이 모듈에는 신규 tests 디렉터리가 없다.

## 4. Q15/Q16 및 관련 품질 게이트는 기존 미수정 범위다

개발 측이 Q15/Q16을 '설계결정으로 미수정'이라고 설명한 범위를 그대로 구분한다. 요청된 업무기준을 충족했다는 뜻은 아니며, 기존 리스크의 수용·보완통제 결정이 별도로 필요하다.

- Q15 검사수량 전량 자동기입: `iatf_process_inspection/models/mrp_production.py:53`~`:54`, `:67`~`:68`, `:79`~`:80`; WO `models/mrp_workorder.py:56`~`:57`; OQC `models/stock_picking.py:49`~`:50`이 그대로다. 단위 검사 approved면 추가량 누적을 생략하는 `mrp_production.py:51`~`:56`도 그대로다.
- Q16 회사격리: `iatf_spc`, `iatf_process_inspection`, `iatf_ppap` security에는 그룹/ACL만 있고 회사 도메인 record rule이 신설되지 않았다. SPC 자동 연구검색도 `process_inspection.py:172`~`:176`에 회사가 없다. SPC 권한을 가진 사용자에게 두 회사의 같은 품목/특성 collecting 연구가 보이면 둘 다 같은 측정을 받는 기존 경로가 유지된다. 단일회사 운영 여부가 위험의 적용범위를 바꾸지만 구현상 경계가 추가된 것은 아니다.
- Q02 OQC hold/조건부 허용: `models/stock_picking.py:27`~`:37`은 미완료/무결과와 fail만 막는다. hold+decided/closed는 두 predicate 모두 false. `_approval_check_approved` 호출은 없다.
- Q03 최초 OQC 생성 후 미판정 예외: `stock_picking.py:23`~`:32`의 같은 트랜잭션 생성→UserError 구조가 그대로다. 본 검토는 소스 동일성을 확인했으며 실제 picking rollback은 이 서브검토에서 실행하지 않았다.
- Q04 검사의 품목/LOT/수량 coverage: `stock_picking.py:23`은 한 검사라도 있으면 생성하지 않고 `:48`은 첫 LOT만 복사. 변경 전후 동일.
- Q05 별도 shipping 검사의 통합: process 게이트가 `iatf.shipping.inspection`을 읽는 변경 없음.
- Q06 다음 WO 시작: `mrp_workorder.py:28`~`:29`는 fail+decided만 차단. fail+closed, hold, draft, 검사없음의 이전 경로 유지. `_create_ipqc_inspection`은 여전히 WO 완료 뒤.
- Q08 PQC 격리: `process_inspection.py:223`~`:240`은 scrap 위치, 전체 quant.quantity, LOT/실제 move-line 수량 없는 move 생성 구조 유지(새 주입 코드 때문에 원래 줄번호보다15행 이동했음).
- Q09 검사완결/승인: `process_inspection.py:147`~`:155`는 종합 result 존재만 확인하고 바로 decided/SPC를 실행. 검사라인 측정/합부/실측수량 검증, 승인 확인은 추가되지 않음. public state 변경·판정 정정 제한도 이 패치에서 추가되지 않음.

게이트 파일 자체의 변경이 없어 그 부분에서 새 우회가 도입됐다는 근거는 찾지 못했다. 새로 확인한 회귀는 **SPC 측정 누락·수기 덮어쓰기**이고, 기존 물류/검사 차단 미비와 분리해서 처리해야 한다.

## 5. 실행·증거와 한계

먼저 실행한 모의 검증은 `work/review_round2/spc_probe.py`이다. 스냅샷에서 AST로 원 메서드를 추출해 자체 작은 레코드셋 모형에서 실행했고, `spc_probe_results.json`에 입력/전후값을 남겼다. 이 AST 스크립트는 Odoo import나 DB 접속을 하지 않았다. 본 검토 전체에서 원본 파일 write, 운영 접속, Git push는 하지 않았다. 모든 probe assert가 통과했다는 뜻은 **위 잔존·신규 결함이 의도한 입력에서 재현됐음**이며 제품 테스트가 통과했다는 뜻이 아니다. fake recordset은 ORM 캐시/권한/트랜잭션/동시성을 모델링하지 않는다.

추가로 루트가 `spc_orm_probe.py`를 **일회용 검토 DB `codex_review2`**, Odoo `18.0-20260609` 이미지/PostgreSQL에서 실제 실행했다. 대상 quality 소스는 읽기 전용이고 MES addon은 설치하지 않았다. 각 case savepoint와 마지막 전체 rollback(`rolled_back=true`)을 로그로 확인했다. 원 로그는 `isolated_orm_probes.log`, SPC JSON 추출은 `spc_orm_results.json`이다.

| 실제 ORM 케이스 | 실행 결과 | 해석 |
|---|---|---|
| 실제0·depends | completed / confirmed=true | 실제0 유지, x1=10 변경시 mean10, count1→2 변경시 mean5, study-n5→1 변경시 mean10으로 갱신. 수정 동작 확인 |
| 출처 접두어 충돌 | completed / confirmed_bug=true | 검사2의 실제라인1·12로 20 실측 누락 재현. 신규 결함 확인 |
| 자동군 수기보완 | completed / confirmed_bug=true | x2~x5 수기값 통계 제외 및 다음 자동값99의 x2 덮어쓰기 재현. 신규 결함 확인 |
| 미완성군 분석 | completed / confirmed_bug=true | 부분군5+1 구성도 analyzed 처리, grand_mean15/range2 확인. 완성검증 미해결 |
| 일반 MO 회사(후속 실행) | completed / confirmed_bug=true | 정상 회사5 창고/MRP fixture로 MO 생성 후 활성회사1에서 PQC helper 실행 → company_id=1의 final 검사. 회사 오귀속 결함 확인 |
| PPAP 회사(후속 실행) | completed / confirmed_fixed=true | 같은 공유품의 회사1 MO 선행 후 회사6 최초 MO → 두 회사 각각의 PPAP 생성·연결. 대상 결함 해결 확인 |

회사 두 사례의 최초 실행은 신규회사에 제조 picking type/sequence를 만들지 않은 테스트 fixture 미비로 대상 hook 검증 전에 실패했다. 이 최초 오류를 제품 결함이나 해결 증거로 세지 않았다. 표준 warehouse를 생성하고 회사별 제조 operation type/sequence·stock 위치를 MO에 명시하도록 fixture만 보완해 `spc_company_probe.py`로 두 사례를 재실행했다. 두 사례 모두 완료했고 마지막 rollback(`rolled_back=true`)을 확인했다. 후속 원 로그는 `isolated_orm_followup.log`, 추출 JSON은 `spc_company_orm_followup_results.json`이다. 원본 모듈은 수정하지 않았다.

위 여섯 ORM 케이스는 실제 Odoo 모델·저장 계산필드·`action_decide`/`action_calculate`·MO 생성 hook·PQC 생성 helper를 실행한 증거다. 전 공정 E2E, 실사용자 권한, 프런트엔드 클릭, 동시성 검증의 대체물은 아니다. 모의 실행 증거와 실제 ORM 결과를 구분한다.

운영 DB의 설치상태/업그레이드 실행·권한별 전체 플로우·생산 장비/현물 차단·동시 트랜잭션·과거 오염 데이터 수량은 미확인이다. iatf_menu 변경 영향은 루트 담당으로 이 문서의 독립 판정에서 제외했다.
