# addons_custom — 모듈 소유권 지도 (겹침 방지)

> **새 기능을 만들기 전에 이 표를 확인하라.** 같은 문제를 푸는 모듈이 이미 있으면
> 새로 만들지 말고 정본을 확장한다. (실사례: 오라클 수요 수신이 두 경로로 만들어져
> 이중 계상 위험 — 2026-08 통합됨. 계획→MO 생성 로직 이중화도 동일 패턴이었음)

## 정본(단일 원장) 선언 — 이 영역은 반드시 해당 모듈로

| 영역 | 정본 모듈 | 비고 |
|---|---|---|
| 오라클 ERP 계획 수신(일자별+시간대별) | `erp_plan_sync` | 계획 화면 버튼은 위임 호출만. 직접 조회 로직은 미설치 폴백 |
| 생산 수요 원장 | `production_planning` (production.demand) | source=oracle/manual/file 구분. 수요를 만드는 새 경로 금지 — 기존 원장에 기록 |
| 사출 생산계획·배정 | `injection_planning` | 형체력/부하분산/안전망 포함 |
| 결재 엔진·결재선 템플릿 | `iatf_approval` | 새 결재 붙일 땐 mixin 사용, 자체 결재 구현 금지 |
| 품의(지출 승인→청구) | `pumui_approval` | |
| 회계 한국화(가드/조회) | `account_kr_guard` / `account_kr_reports` | |
| 급여 | `hr_payroll_kr` | 수치는 전부 데이터(요율·브래킷) |
| IATF 검사·추적·부적합 등 | `iatf_*` (개별 모듈) | 자동생성 훅은 sudo, env.get 은 is None 검사 |
| 시리얼·LOT 발행(14자리) | (odoo_gh) `escon_serial` | engel_injection 등에서 lot 임의 생성 금지 |
| 설비 예비부품 재고·부족 판정 | `iatf_equipment` (iatf.equipment.spare) | `stock.quant` 는 **읽기 전용**(qty_available). 발주는 아직 미구현 — 붙일 때 아래 주의 참조 |
| 예비부품 분류체계(부문/공정/설비군/기종) | `iatf_equipment` (iatf.spare.category) | 레거시 SPMSRT 4자리 한 칸을 자리별 트리로 편 것. 새 분류 모델 만들지 말 것 |
| 부품↔설비 적용(다대다) | `iatf_equipment` (iatf.spare.application) | 부품이 어느 설비에 들어가는지의 정본. `spare.equipment_id`(1:N)는 18.0.1.3.0 에서 제거됨 |
| 자재 발주(원재료·외주) | `injection_planning` / `supplier_portal_purchase` | 예비부품 쪽에서 PO 를 직접 만들지 말 것. 발주 경로가 둘로 갈라지면 이중 발주가 된다 |
| 금형 관리기준(등급·주기·온도 상하한) | `iatf_mold` (iatf.mold) | 점검·세척·온도 판정의 기준은 전부 여기. 온도 합·부 비교는 `judge_temp()` 하나만 쓴다(`check_temp_in_spec()` 은 현행 기준으로 그것을 부르는 편의 함수) — 판정 로직을 각 기록 모델에 복사하지 말 것 |
| 금형 세척 실적 | `iatf_mold` (iatf.mold.maintenance, type=`clean`) | 세척 전용 모델 만들지 말 것. 완료(done) 건만 실적으로 센다 |
| 시사출(T/O) 보고서 | `iatf_mold` (iatf.mold.tryout) | 심사 증빙 문서라 `ondelete=restrict`. 금형은 삭제 말고 폐기(disposed) 로 |
| 금형 일상/정기 점검 | `iatf_mold` (iatf.mold.check) | 설비 점검(`iatf.daily.check`) 과 별개 원장. **공구·구역·시설용 공통 점검 시트(`iatf.check.sheet`, 요청서 2항)로 금형을 덮지 말 것** — 금형은 마스터에 주기가 있고 누락 판정이 `iatf.mold` 위에 산다 |
| 금형 예열/온도 측정 | `iatf_mold` (iatf.mold.temp.log) | 금형 온도의 **유일 원장**. 시사출·점검 기록에 온도 필드를 따로 두지 말 것. 기준 상·하한은 **측정 시점 스냅샷**(저장)이며 마스터 개정에 끌려가지 않는다. 합·부 비교는 `iatf.mold.judge_temp()` 하나만 쓴다(현행 기준 재평가는 `current_spec_result` 참고값) |
| 범용 점검 일지(공구·검사마스터·설비/시설·구역) | `iatf_work_environment` (iatf.check.sheet / iatf.check.record) | 전동공구 토크·통전검사·바코드 마스터·건조기 필터·분쇄기·배합기·냉각수/작동유·소화기 = **전부 이 모델 하나**. 대상별 전용 모듈·모델 금지 |
| 작업환경 실측(온습도·조도)·5S 점수 | `iatf_work_environment` (iatf.environment.check) | 구역 기준(`iatf.work.area`) 대비 실측·5S 5개 점수는 여기가 정본. 점검 시트로 옮기지 말 것 |
| 산업안전 위험성평가 | `iatf_work_environment` (iatf.safety.assessment) | 작업별 유해위험요인 × 가능성/중대성 + 감소대책 이행. **`iatf.risk.register` 와 다른 원장** — 아래 경계 참조 |
| 아차사고·사고 이력 | `iatf_work_environment` (iatf.safety.incident) | 아차사고를 사고와 **같은 원장**에 둔다. 분리하면 "사고 0건" 숫자만 남고 예방활동 증빙이 사라진다 |
| 안전점검(소화기·비상구·방호장치) | `iatf_work_environment` (iatf.check.sheet, `is_safety=True`) | **네 번째 점검 원장을 만들지 말 것.** 주기·미실시 판정 구조가 일반 점검과 같아 플래그로만 구분한다 |
| 재생재 배합 상한 기준 | `iatf_traceability` (iatf.blend.standard) | 품목(+수지)별 상한·분모정의·고객승인. 상한 숫자를 코드나 다른 모델에 박지 말 것 |
| 분쇄일지(스크랩→재생재) | `iatf_traceability` (iatf.regrind.log) | 재생재 로트의 **출처**. 분쇄기 자체의 일상점검은 `iatf.check.sheet` 쪽 |
| 배합일지(투입 비율·합부) | `iatf_traceability` (iatf.blend.log + .line) | LOT별 신재/재생재/첨가제 투입과 상한 대비 판정. 재생재 줄은 분쇄일지를 가리켜야 완료된다 |

### 점검 원장 경계 (헷갈리기 쉬움)
- **금형** → `iatf.mold.check` (주기가 금형 마스터에 있고 누락 판정이 `iatf.mold` 위에 산다)
- **설비 대장에 등록된 설비의 일상점검** → `iatf.daily.check` (iatf_equipment)
- **구역 환경 실측·5S 점수** → `iatf.environment.check`
- **그 외 전부(공구·검사마스터·시설·소화기 등)** → `iatf.check.sheet` + `iatf.check.record`

### 배합 판정의 두 가지 함정 (SQ 1_10 / 3_4)
- **분모를 코드가 정하지 않는다.** 재생률을 수지 기준(신재+재생재)으로 세는 회사와
  총 투입량(첨가제 포함) 기준으로 세는 회사가 갈린다. 개발이 임의로 고르면 회사 기준과
  다른 판정이 그대로 증빙이 된다. 그래서 분모는 기준 마스터의 `ratio_basis` 가 정한다.
- **기준은 배합일 시점으로 스냅샷한다.** `standard_id` 만 들고 있으면 나중에 상한을
  완화하는 순간 과거의 초과 배합이 합격으로 뒤집힌다. 그래서 `limit_ratio` /
  `limit_additive_ratio` / `ratio_basis` 를 배합일지에 복사해 저장한다.

`iatf.blend.standard` 에는 다중회사 레코드 규칙이 없다. `_standard_for()` 가 회사를
직접 거른다 — 이 필터를 지우면 남의 법인 상한으로 우리 배합이 판정된다(적대적 검증에서
실제로 재현됨). 기준이 없을 때는 `ok` 가 아니라 `pending` 으로 남기고, 완료는 막지 않되
「기준 초과·판정불가 배합」 목록으로 적발한다. 원인이 작업자가 못 고치는 마스터 공백이라
완료를 막으면 기록 자체가 안 남기 때문이다.

### 리스크 원장 경계
- **사업·공정 리스크와 기회 (IATF §6.1)** → `iatf.risk.register`
- **작업자 유해·위험요인 (산업안전, SQ 6_1)** → `iatf.safety.assessment`

둘은 구조가 다르다. 후자는 개선 전/후 위험성 비교와 감소대책 이행 추적이 필수라
전자에 얹으면 어느 쪽 증빙도 되지 않는다.

### 기한 경과 판정 방식 (모듈별로 다름 — 통일하지 말 것)
- `iatf.check.sheet` → 주기가 마스터에 있으므로 `next_due`(저장) + `is_overdue`(비저장 + `search=`)
- `iatf.audit` / `iatf.training.record` / `iatf.competence.matrix` → 계획일·만료일이 **이미
  일반 Date 컬럼**이라 검색뷰 도메인만으로 충분하다. 필드를 새로 만들지 않았다.
  (원칙은 같다 — 오늘 날짜에 의존하는 판정은 절대 저장하지 않는다)

`iatf.check.record.line._check_result_matches_spec` 와
`iatf.mold.check.line._check_result_matches_spec` 는 **같은 허위기재 차단 규칙의 복제본**이다.
한쪽만 고치면 구멍이 생긴다. 공용 mixin 으로 합치는 작업은 PR #31 병합 후.

## 세션 작업 규칙

### 사출 담당자 자동 생산과 IATF 연동 (2026-09-09)

- `iatf_control_plan`의 MO 생성 훅은 해당 MO 회사의 승인된 관리계획서를 내부 조회하여 연결한다. 생산 담당자에게 관리계획서 편집권을 부여하지 않는다.
- `iatf_ppap`의 초도 MO 훅은 MO 회사의 PPAP 요청을 내부 조회·생성한다. PPAP 승인·수동 편집 권한과 분리한다.
- `iatf_training`의 생산 완료 경고는 MO 회사 소속 작업자의 역량 갭만 내부 조회한다. 교육 원장 접근권한을 확대하지 않는다.
- `iatf_process_inspection`의 완료 훅은 MO 완료 처리 뒤 해당 생산 실적에서 공정검사를 내부 생성·누적한다. 공개 수동 입력 API에 포괄 sudo를 추가하지 않는다.
- 위 네 훅은 같은 MO 생성/완료 경로에 겹친다. 변경 시 `injection_worksite`의 담당자 Bearer 생산 회귀 테스트(생성→시작→중지→재개→단위 실적→계획 종료)로 함께 검증한다.

1. 수요·정산·시리얼·결재처럼 "원장" 성격 데이터는 **만들지 말고 정본에 기록**한다.
2. 같은 모델에 두 모듈이 훅을 걸면 실행 순서·중복을 검토하고 이 파일에 기록한다.
3. 작업 단위별 브랜치 → PR. 다른 세션 활성 브랜치에 얹지 않는다.
4. 완료 전 검증: 원격 존재(ls-remote) + 테스트 그린 + (해당 시) 심볼 스캔.
5. **`-u` 는 미설치 모듈에 아무 일도 하지 않는다.** exit=0 을 검증으로 착각하지 말 것.
   검증 DB 에서 `ir_module_module.state` 를 먼저 확인하고, 미설치면 `-i` 로 설치한다.
6. **필드를 모델에서 지워도 컬럼은 남는다.** Odoo 는 경고 한 줄만 찍고 컬럼을
   그대로 둔다. 지운 필드가 `required=True` 였다면 NOT NULL 컬럼이 남아 **그
   모델에 새 레코드를 만들 때마다 insert 가 실패한다.** 로컬 새 DB 에서는
   안 보이고 운영 업그레이드에서만 터진다. 반드시 마이그레이션에서
   (1) 값을 옮기고 (2) `DROP COLUMN` 한다.
   (실사례: `iatf.equipment.spare.equipment_id` → `iatf.spare.application`,
   `migrations/18.0.1.3.0/post-migration.py`)
7. **분류 트리에 제약을 걸 때는 '분류 쪽 write' 도 막았는지 본다.** 부품에
   `@api.constrains("category_id")` 만 걸면, 부품은 그대로 두고 **분류의
   `level` 을 바꿔** 묶음 노드로 만드는 우회가 열린다. 양쪽 모델 모두에서 막는다.
8. **비저장 계산 필드 위에 `store=True` 를 얹지 않는다.** `product.qty_available`,
   `iatf.equipment.mtbf` 처럼 비저장인 값에 의존하면 Odoo 가 재계산 트리거를 걸지
   못해 값이 굳는다. 대신 비저장으로 두고 `search=` 메서드로 검색만 살린다.
   (검색뷰 filter/group_by 도 같은 제약 — `search=` 없으면 뷰 검증에서 실패하고,
   group_by 는 SQL 컬럼이 없어 아예 불가)
7. **오늘 날짜에 의존하는 판정은 저장하지 않는다.** `is_*_overdue` 류를 `store=True`
   로 두면 다음 재계산 전까지 값이 굳어 기한이 지나도 '정상' 으로 보인다. 대신
   예정일(`next_*_due`)만 저장하고, 경과 여부는 비저장 + `search=` 로 SQL 도메인을
   돌려준다.
8. **'미설정' 과 '0' 을 섞지 않는다.** Float/Integer 기준값(온도 상하한, 주기)이 0 이면
   판정하지 않는다(`no_spec`). 0 을 기준으로 읽으면 기준을 넣은 적 없는 대상이
   전부 부적합으로 찍혀 없는 결함을 만들어낸다.
9. **SQ/IATF 증빙 데이터에 데모·샘플 실적을 넣지 않는다.** 채점 기준에 허위기재 시
   다수미흡(25%) 이 명시돼 있다. 없는 실적은 없는 채로 두고 기준·계획으로 설명한다.
10. **기준이 판정한 합·부를 사람이 덮어쓸 수 있으면 그게 허위기재 경로다.**
    `compute=..., store=True, readonly=False` 만으로는 못 막는다 — 의존 필드가 안 바뀌는
    write(결과만 덮어쓰기)에서는 재계산이 돌지 않고, 뷰의 `readonly` 는 서버에서
    강제되지 않는다. 반드시 `@api.constrains` 로 "기준의 판정 ≠ 저장된 결과" 를 막는다.
    (`iatf.mold.check.line._check_result_matches_spec`)
11. **'실적' 은 완료(done) 건만 센다.** 작성 중(draft)·계획(planned) 기록을 이행실적으로
    세면 없는 이행이 생긴다. 그리고 **항목이 비어 있는 기록은 '양호' 가 아니라 '미완료'** 다
    — 빈 점검표가 양호로 집계되는 것이 크리아 4_1 감점("점검표 작성 일부 누락")의 정체다.
12. **완료(done) 된 실적은 잠근다.** 점검일·라인·기준 스냅샷·측정값은 완료 후 write/unlink 를
    서버에서 막는다(`iatf.mold.check`, `iatf.check.record` 와 각 라인). 고쳐야 하면 '작성 중'
    으로 되돌리고(상태 변경은 chatter 에 남는다) 고친 뒤 다시 완료한다. 완료 후에도 열어 두는
    필드는 `_DONE_EDITABLE` 로 명시한다. — 2026-09-10 제3자 검토 Q10 에서 "완료 후 증빙 변경"
    경로가 지적됐다.
13. **기준이 있는 항목은 측정값 없이 판정하지 못한다.** 측정값 0(미기입)은 `no_value` 인데,
    이때 결과를 사람이 '양호' 로 넣을 수 있으면 상한이 있는 항목을 재지 않고 통과시키는
    경로가 된다. `_check_result_matches_spec` 이 `no_value` + 수동 판정을 막는다. (Q12)
14. **메뉴는 `iatf_menu` 가 만들지 않고 옮긴다.** 각 모듈은 자기 메뉴(뿌리 포함)를 자기 XML 에
    갖고, `iatf_menu` 는 `<menuitem id="모듈.xmlid" parent="새자리"/>` 로 **뿌리를 재배치**만 한다.
    `iatf_menu` 안에 같은 action 의 menuitem 을 새로 만들면 같은 화면이 두 메뉴에 달린다
    (2026-09-10 리허설에서 88건 발견 — "양쪽 보존" 충돌 해결의 부산물). 비게 된 옛 그룹은
    지우지 말고 `active=False` (모듈 단독 -u 때 되살아난다). 모듈을 단독 -u 한 뒤 메뉴가
    흐트러지면 `iatf_menu` 를 함께 -u 한다.
