# CAMS 통합 인계 문서 — 메인 개발자(레포 소유자)용

작성 2026-07-09 · 대상: escon-odoo/odoo_gh · wilcoco/odoo 소유자 · 목적: 우리 작업분(8 브랜치)의 **통합 요청 + 충돌 해결 + 통합 후 검증** 인계.
동봉: [PR_패키지.md](PR_패키지.md)(PR 제목·본문·순서) · 도메인별 설계·검증 문서(하단 목록).

---

## 0. 한눈에
- **2개 저장소, 8개 feature 브랜치**, 전부 cams_sim3에서 e2e 검증 완료. main 미반영.
- **핵심 통합 리스크는 딱 3가지**: ① injection_worksite manifest **버전 충돌**(3브랜치), ② `product_template.py`/뷰 **양쪽 필드 병합**, ③ **마이그레이션 순번 재정렬**. 나머지는 additive라 자동 머지.
- 통합은 "코드 머지"로 끝이 아니라 **실 DB -u + 실값 입력 + 검증 시나리오**까지가 완료 기준.

---

## 1. 통합 대상 (8 브랜치)

### escon-odoo/odoo_gh
| # | 브랜치 | 모듈 | 요지 | base |
|---|---|---|---|---|
| ① | fix/settlement-review | injection_worksite, gh_vendor_settlement, dashboard | 정산 결함·동시성·권한(시뮬 검증) | main |
| ② | feat/provisional-pricing | gh_provisional_pricing(신규) | 가/정 소급(매입·매출·B표준갱신) | **①** |
| ③ | feat/injection-costing | injection_worksite | capability→표준원가 공정 브리지 | main |
| ④ | feat/injection-actual-cost | injection_costing(신규) | 실제원가·차이4분해·소급·정책 | **③** |
| ⑤ | feat/plc-weight-capture | injection_worksite | 실측중량·사출품 플래그·장애 백필 | main |

### wilcoco/odoo
| # | 브랜치 | 모듈 | 요지 | base |
|---|---|---|---|---|
| ⑥ | fix/sim-found-defects | injection_planning, iatf_* | 계획 재계산 가드(F1)·IATF 6건 | main |
| ⑦ | feat/planning-safety-nets | injection_planning | 안전망·가시화·G1·G3 | **⑥** |
| ⑧ | feat/planning-optimization | injection_planning | 형체력·유효능력·부하분산(G4·G5) | **⑦** |

머지 순서: **① → ② / ③ → ④ / ⑤** (odoo_gh) · **⑥ → ⑦ → ⑧** (wilcoco). 스택은 부모 머지 후 base 자동 전환.

---

## 2. ★ 충돌 해결 가이드 (injection_worksite — ①③⑤가 공유)

이 3개가 injection_worksite를 동시에 건드립니다. **머지 순서 권장: ① → ③ → ⑤** (⑤가 파일을 가장 많이 바꾸므로 마지막에 흡수).

### 2-1. `__manifest__.py` version (🔴 반드시 수동)
현재 브랜치 값이 제각각(main 2.2 / ① 2.5 / ③ 2.3 / ⑤ 2.5) — **충돌 확정**.
- **해결**: 머지할 때마다 무시하고, **최종 통합 시 단일 값으로 리넘버**. 권장 최종값 **`18.0.3.0`**(모든 브랜치값보다 큼).
- 이유: 프로덕션 DB는 2.2. 최종을 3.0으로 두면 2.2→3.0 업그레이드 시 그 사이 마이그레이션이 전부 1회 실행됨.

### 2-2. `migrations/` 순번 (🔴 반드시 확인)
- ⑤가 **`18.0.2.4/post-flag_injection_parts.py`**(사출품 플래그 백필) 추가. 유일한 신규 마이그레이션.
- ①은 버전만 2.5로 올렸고 신규 마이그레이션 없음(기존 최고 2.2).
- **해결**: `18.0.2.4/post-flag_injection_parts.py`를 그대로 유지(2.2 < 2.4 < 3.0 이므로 prod 업그레이드 시 실행됨). 폴더명 변경 불필요. 최종 manifest만 3.0으로.

### 2-3. `models/product_template.py` (🔴 양쪽 필드 다 유지)
- ①(settlement)이 **`settle_by_ton`** 추가, ⑤(plc-weight)가 **`is_injection_part`** 추가. 둘 다 `x_injection_min/maxweight` 다음에 붙임 → **같은 위치 충돌**.
- **해결**: 충돌 마커에서 **양쪽 필드 블록 모두 채택**(둘 다 살림). 순서 무관.

### 2-4. `views/product_template_views.xml` (🔴 양쪽 필드 다 유지)
- ①·⑤가 '사출 정보' group에 각각 필드 추가 → 충돌. **양쪽 `<field>` 다 유지**.

### 2-5. 충돌 없음(참고) — additive
- ③: `machine_mold_capability_cost_bridge.py`(신규 파일) + `__init__.py`에 import 1줄
- ⑤: `machine_mold_capability_bridge.py`(기존 파일 편집 — `_flag_injection_products` + `InjectionMoldWorksiteBridge` 추가), `plc_controller.py`, `mrp_production.py`, `production_record.py` — ①③과 안 겹침
- ③과 ⑤의 __init__: ③만 cost_bridge import 추가(⑤는 기존 파일 수정이라 __init__ 무변경) → 충돌 없음

> **요약**: injection_worksite 통합 시 손볼 건 딱 4곳 — manifest 버전(3.0), product_template.py·뷰(양쪽 필드), 마이그레이션 유지. 전부 "양쪽 다 살리기".

---

## 3. 통합 후 검증 절차 (완료 기준)

### 3-1. 설치/업그레이드 (스테이징 먼저, 절대 prod 직행 금지)
```
# main 통합 브랜치에서
odoo -u injection_worksite,injection_costing,gh_provisional_pricing,gh_vendor_settlement,injection_planning \
     -d <staging_db> --stop-after-init
```
확인: 에러 없이 `Modules loaded` · **18.0.2.4 마이그레이션 실행 로그**(사출품 백필) 확인.

### 3-2. 마이그레이션 결과 (사출품 백필)
```sql
-- 금형/capability에 걸린 제품이 사출품+serial로 백필됐나
SELECT default_code, is_injection_part, tracking FROM product_template
WHERE is_injection_part = TRUE;   -- 사출품만 TRUE, tracking='serial'
```

### 3-3. 도메인별 스모크 테스트 (스테이징)
| 영역 | 확인 |
|---|---|
| 생산계획 | 수요 투입→계획 계산→**계획라인 사출품만**(외주 제외), 경고 채터 게시, 형체력 필터(실값 있으면) |
| 사출 PLC | /api/plc/complete 실측중량+마커 기록, 미지 2xxx 시리얼 백필 수용, 재전송 멱등 |
| 원가 | `실제원가(관리)>MO 실제원가` 재집계 → **대사정합**(실제−표준=가격+수량+능률) 전건, 커버리지 표시 |
| 정산 | 조립 MO 완료→accrual, 월정산 위저드→매입계산서, 동시 클릭 1장 |
| 소급 | 계약단가 정단가 확정→소급전표 초안+통지, frozen 불변·recon_ok |
| 안전망 | 수요 미매핑/다중BOM/월마감 불일치 시 **채터·알림 뜨는지** |

### 3-4. 회귀 가드 (반드시)
- **회계 무변경 확인**: 원가작업 전후 `stock.valuation.layer` 건수·원가법(standard/manual_periodic) 불변 — 관리원가는 회계 정본 아님(재무제표 영향 0이어야).
- 기존 MO 완료 흐름(정상 PLC): 시리얼 lot 자동지정 되는지(⑤에서 tracking=serial 자동화되며 완료에 시리얼 필수가 됨 — 정상경로도 영향).

---

## 4. 통합 후 필요한 실값 입력 (미입력 시 기능은 돌지만 값이 대표치)
| 대상 | 필드 | 화면 |
|---|---|---|
| 워크센터 | costs_hour(시간당원가), **x_clamping_force_ton(형체력)** | 사출 설정>작업장 |
| 금형 | changeover_hours, **required_clamping_ton(요구형체력)** | 마스터>금형 |
| capability | cycle_time·cavity·defect_rate 실측 | 마스터>사출기-금형 조합 |
| 원재료/외주 | 실제 계약단가·톤단가 | 계약 톤단가 / 계약단가(가/정) |
| 제품 | min_lot·max_inventory·injection_base_code | 사출 제품/부품 |
> 화면별 입력 가이드: [CAMS_화면별_입력가이드.docx] (스크린샷 16컷).

---

## 5. 미결·협의 (JWY/현장/회계가 결정 — 우리 코드 밖)
| # | 사안 | 상태 |
|---|---|---|
| 1 | **시리얼 표준 단일화** — 구조도 14자리(1=Odoo/2=PLC폴백/3=비상) vs 현재 코드 10자리·"2=임시별칭" 충돌 | 🔴 3자 협의 최우선. 확정되면 우리가 생성기·백필 정렬 |
| 2 | PLC 미들웨어 송신 규격 — payload에 `weight`·`produced_at` 포함 | 미들웨어/하드웨어 |
| 3 | 이종검사 대상 = 대장 고정 → **MO 소비라인 실시간 조회**로 전환(is_injection_part 읽기) | JWY(그의 검사모듈) |
| 4 | 원재료 조달 — PO 생성(G6) vs 소요통보(무발주) 일원화 | 정책 |
| 5 | 컬러코드 — 기존 escon.color.code/ALC 체계에 사출 샘플 연결 | JWY |
| 6 | 재무 자동분개 2단계(valuation 전환) | CFO/회계(파킹) |
| 7 | 매출 소급 수정세금계산서 사유코드 | 세무 |

---

## 6. 롤백·리스크
- **모든 신규 모듈은 독립 앱**(injection_costing·gh_provisional_pricing) — 미설치 시 기존 무영향. 문제 시 해당 모듈만 uninstall.
- **⑤ tracking=serial 자동화가 유일한 광범위 영향** — 사출품 완료에 시리얼 필수가 됨. 정상 PLC 완료에서 lot 자동지정(mrp_production 완료 훅)로 대응했으나, **스테이징에서 실제 PLC 시퀀스로 한 번 더 확인 권장**.
- 회계 valuation 미변경이 통합의 대전제 — 3-4 회귀 가드가 깨지면 통합 보류.

---

## 7. 동봉 문서 (도메인별 근거)
전체구조 `CAMS_전체이해_가이드` · 운영매뉴얼 `CAMS_Odoo_운영매뉴얼_상세판` · 원가 `실제원가_관리분석_설계`/`원가시스템_회계CFO_검증보고서`/`재무자동분개_2단계_설계` · 소급 `가단가_정단가_설계명세` · 계획 `사출생산계획_구조분석_매뉴얼`/`사출계획_배정최적화_검토` · 안전망 `안전망_감사_가시화_배치` · 시뮬 `회사운영_전체시뮬레이션_원가통합` · PR `PR_패키지`.

---

## 요청 요약 (개발자에게)
> 위 8 브랜치를 §1 순서로 머지 부탁드립니다. injection_worksite는 ①③⑤가 겹치니 **§2 충돌 가이드**(manifest 3.0으로 리넘버 + product_template 양쪽 필드 + 2.4 마이그레이션 유지)만 지켜주시면 나머지는 additive입니다. 머지 후 **§3 검증(특히 회계 무변경 회귀 가드 + tracking=serial 정상경로)** 을 스테이징에서 확인해주세요. §5 협의사항 중 **시리얼 표준 단일화**가 최우선 결정입니다.
