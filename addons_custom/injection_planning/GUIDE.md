# 사출 생산계획 자동화 모듈 (injection_planning)

## 개요

Odoo 18 Community 기반 사출성형 생산계획 자동화 모듈입니다.
Oracle ERP에서 완제품 수요를 받아 BOM 전개 → 사출 부품 식별 → 사출기 스케줄링 → MO(제조오더) 자동 생성까지 전 과정을 자동화합니다.

---

## 1. 모듈 구조

```
injection_planning/
  controllers/
    api.py                     # REST API (Bearer 토큰 인증)
  data/
    cron.xml                   # 자동 스케줄링 Cron Job
    sequence.xml               # 계획번호 시퀀스 (PLAN-YYYY-NNNN)
  models/
    mold.py                    # 금형 마스터
    machine_mold_capability.py # 사출기-금형 조합 능력
    machine_availability.py    # 사출기 가동 일정
    planning_config.py         # 계획 설정 (Oracle 연결, 변수)
    production_demand.py       # 수요 데이터
    planning_run.py            # 계획 실행 (메인 스케줄링 엔진)
    planning_line.py           # 계획 상세 라인
    planning_daily_summary.py  # 일별 분석 (차트 데이터)
    product_planning.py        # product.product 확장 (최대재고, 최소로트)
    mrp_production.py          # mrp.production 확장 (planning_run_id)
  wizards/
    import_demand_wizard.py    # CSV 수요 파일 업로드
    generate_mo_wizard.py      # MO 생성 확인 위자드
    generate_demo_wizard.py    # 테스트 샘플 데이터 일괄 생성
  views/
    *.xml                      # 폼/리스트/검색/그래프 뷰
    menu.xml                   # 메뉴 구성
  security/
    security.xml               # 그룹 (사용자/관리자)
    ir.model.access.csv        # 접근 권한
```

---

## 2. 데이터 모델

### 2.1 마스터 데이터

| 모델 | 설명 | 주요 필드 |
|------|------|-----------|
| `injection.mold` | 금형 | code, cavity_count, changeover_hours, guaranteed_shots |
| `injection.machine.mold.capability` | 사출기-금형 조합 | workcenter_id, mold_id, cycle_time, defect_rate, hourly_capacity(자동계산) |
| `injection.machine.availability` | 사출기 가동일정 | workcenter_id, date, day_shift_hours, night_shift_hours |
| `injection.planning.config` | 계획 설정 | Oracle 연결, 안전재고일수, 교대시간, 기본 불량율 등 |

### 2.2 트랜잭션 데이터

| 모델 | 설명 | 주요 필드 |
|------|------|-----------|
| `injection.production.demand` | 수요 데이터 | demand_date, product_id, quantity, source(oracle/manual) |
| `injection.planning.run` | 계획 실행 | plan_date_from/to, state, demand_ids, line_ids, summary_ids |
| `injection.planning.line` | 계획 라인 | workcenter_id, mold_id, product_id, planned_qty, changeover_needed |
| `injection.planning.daily.summary` | 일별 요약 | product_id, plan_date, demand_qty, planned_qty, safety_stock_qty, stock_end |

### 2.3 Odoo 표준 모델 확장

| 모델 | 추가 필드 |
|------|-----------|
| `product.product` | max_inventory_qty (최대재고), min_lot_size (최소로트) |
| `mrp.production` | planning_run_id (계획 실행 연결) |

---

## 3. 핵심 워크플로우

```
┌──────────────────────────────────────────────────────────┐
│  ① 수요 입력                                              │
│     Oracle 자동 조회 / CSV 파일 업로드 / 수동 입력          │
│     (완제품 기준, 예: 프론트 범퍼 ASSY 120개)              │
└────────────────────┬─────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────┐
│  ② BOM 전개 (1단계)                                       │
│     완제품 → 사출 부품 식별                                │
│     프론트 범퍼 ASSY → 범퍼 쉘 x1 + 브라켓 x2             │
└────────────────────┬─────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────┐
│  ③ 순수요 계산                                            │
│     필요량 = 수요 + 안전재고 - 현재재고                     │
│     최대재고 제한 적용                                      │
└────────────────────┬─────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────┐
│  ④ 사출기 배정 + 스케줄링                                  │
│     사출기-금형 조합 능력 기반 배정                          │
│     불량율 보정, 초기불량 가산, 최소로트 적용                 │
│     금형 교체 최소화 (같은 금형 연속 배치)                    │
│     가동일정 반영 (비가동일 건너뛰기)                        │
└────────────────────┬─────────────────────────────────────┘
                     ▼
┌──────────────────────────────────────────────────────────┐
│  ⑤ 검토 → 확정 → MO 자동 생성                             │
│     계획 라인 검토 후 확정 → Odoo 제조오더 일괄 생성         │
│     MO에 BOM 연결 → 원재료 자동 소비 (2단계 BOM)           │
└──────────────────────────────────────────────────────────┘
```

---

## 4. BOM 구조 (2단계)

```
완제품 (Oracle 수요 대상)
 └─ BOM 1단계 ─→ 사출 부품 (금형으로 생산)
                    └─ BOM 2단계 ─→ 원재료 (수지, 첨가제)

예시)
프론트 범퍼 ASSY (86500-BS000EBB)
 ├─ 프론트 범퍼 쉘 (INJ-BF-001) x1
 │    ├─ PP 수지 (RAW-PP-001) 2.5kg
 │    └─ 블랙 마스터배치 (RAW-MB-BK01) 0.05kg
 └─ 범퍼 브라켓 (INJ-BK-001) x2
      └─ PA66-GF30 (RAW-PA66GF-001) 0.35kg
```

---

## 5. 사용법 (운영 매뉴얼)

### 5.1 초기 설정 (1회)

1. **계획 설정** (생산계획 > 설정 > 계획 설정)
   - 안전재고 일수: 3.5일 (기본)
   - 교대 시간: 주간 8h, 야간 8h
   - 기본 불량율: 2.0%
   - Oracle 연결 정보 (운영 시)

2. **금형 등록** (생산계획 > 마스터 > 금형)
   - 금형 코드, 캐비티 수, 교체 시간, 보증 샷수

3. **사출기-금형 조합** (생산계획 > 마스터 > 사출기-금형 조합)
   - 사출기 + 금형 조합별 사이클타임, 불량율 설정
   - 시간당 생산능력 자동 계산: (3600 / 사이클타임) x 캐비티수

4. **제품 설정**
   - 완제품: Oracle 품번 코드로 등록
   - 사출 부품: INJ-코드로 등록 + 최대재고, 최소로트 설정
   - 원재료: RAW-코드로 등록 + standard_price 설정
   - BOM 1단계: 완제품 → 사출 부품
   - BOM 2단계: 사출 부품 → 원재료

5. **공급업체 등록** (구매 > 공급업체)
   - 원재료별 공급업체, 구매가격, 최소주문량, 리드타임

### 5.2 일상 운영

1. **계획 실행 생성** (생산계획 > 계획 실행 > 생성)
   - 계획 시작일 / 종료일 설정

2. **수요 가져오기** (3가지 방법)
   - `[수요 가져오기]` 버튼 → Oracle 자동 조회
   - `[파일 업로드 (CSV)]` 버튼 → CSV 파일 임포트
   - `[수동 수요 추가]` 버튼 → 직접 입력

3. **가동 일정 설정**
   - `[가동 일정 설정]` 버튼 → 기간 내 사출기별 가동시간 일괄 생성
   - 필요 시 개별 수정 (정비일, 휴일 등)

4. **계획 계산**
   - `[계획 계산]` 버튼 → BOM 전개 + 순수요 + 스케줄링 자동 실행
   - 결과: 계획 라인 목록 + 일별 분석 차트

5. **검토 및 확정**
   - 계획 라인 검토 (수량, 사출기 배정, 금형 교체 등)
   - `[확정 (MO 생성)]` 버튼 → 제조오더 일괄 생성

6. **일별 분석 확인**
   - `[일별 분석]` 스탯 버튼 → 라인 차트, 피벗 테이블
   - 제품별 소요량/생산량/재고량/안전재고 일별 추이

### 5.3 자동 모드 (Cron)

계획 설정에서 `자동 MO 생성` 활성화 시, Cron이 매일 자동 실행:
Oracle 수요 조회 → 계획 계산 → MO 생성

---

## 6. 스케줄링 알고리즘 상세

### 6.1 BOM 전개
- 수요는 완제품 기준으로 들어옴
- BOM 1단계를 찾아서 사출 부품별 소요량 산출
- BOM이 없거나 라인이 비어있으면 해당 제품 자체를 사출품으로 간주

### 6.2 순수요 계산
```
안전재고 = 일평균수요 x 안전재고일수 (기본 3.5일)
순수요 = 수요량 + 안전재고 - 현재재고
if 최대재고 > 0:
    순수요 = min(순수요, 최대재고 - 현재재고)
```

### 6.3 사출기 배정
- 각 사출 부품에 대해 가능한 사출기-금형 조합 검색
- 시간당 생산능력이 가장 높은 조합 선택
- 같은 금형을 사용하는 작업을 연속 배치 (교체 횟수 최소화)

### 6.4 수량 보정
```
보정수량 = ceil(순수요 / (1 - 불량율/100))
if 금형교체:
    보정수량 += 초기불량수
if 보정수량 < 최소로트:
    보정수량 = 최소로트
```

### 6.5 시간 배치
- 사출기별 가동일정 참조 (day_shift_hours + night_shift_hours)
- 남은 시간 부족 시 다음 가용일로 자동 이동
- 비가동일(주말, 정비) 건너뛰기

---

## 7. 자동 분개 (회계 연동) 사전 조건

MO 완료 시 Odoo가 자동으로 회계 분개를 생성하려면:

| 조건 | 설정 위치 | 설명 |
|------|-----------|------|
| 제품 원가 (standard_price) | 제품 > 일반정보 > 원가 | 분개 금액 기준 |
| 재고 평가 = 자동 | 제품 카테고리 > 재고 평가 > Automated | 수동(Manual)이면 분개 안됨 |
| 회계 계정 매핑 | 제품 카테고리 > 계정 속성 | 재고입고/출고/평가 계정 |
| 공급업체 + 구매가격 | 제품 > 구매 탭 | 구매 입고 시 분개 |
| BOM 2단계 | 사출 부품 BOM > 원재료 | MO 완료 시 원재료 자동 소비 |

### 분개 흐름
```
① 원재료 구매 입고
   차) 원재료 재고계정     대) 매입채무

② MO 시작 (원재료 출고)
   차) 재공품(WIP)         대) 원재료 재고계정

③ MO 완료 (사출 부품 입고)
   차) 제품 재고계정       대) 재공품(WIP)

④ 출하 (매출)
   차) 매출원가            대) 제품 재고계정
```

**중요:** 제품 카테고리에서 `재고 평가 = Automated`로 설정해야 합니다.
개별 제품마다 설정하는 것이 아니라, 카테고리 단위로 한 번만 설정합니다.
- "원재료" 카테고리 → 원가법: 표준원가, 재고평가: Automated
- "사출 부품" 카테고리 → 원가법: 표준원가, 재고평가: Automated
- "완제품" 카테고리 → 원가법: 표준원가, 재고평가: Automated

---

## 8. REST API

Bearer 토큰 인증 방식. Go 미들웨어/외부 시스템 연동용.

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/v1/planning/mold` | GET | 활성 금형 목록 |
| `/api/v1/planning/capability` | GET | 사출기-금형 조합 목록 |
| `/api/v1/planning/run` | GET | 최근 계획 실행 목록 |

---

## 9. 샘플 데이터 생성 (테스트용)

**메뉴:** 생산계획 > 설정 > 샘플 데이터 생성

`[생성]` 버튼 한 번으로 아래 데이터가 자동 생성됩니다:

| 항목 | 수량 | 상세 |
|------|------|------|
| 완제품 | 4종 | Oracle 품번 (86500-BS000EBB 등) |
| 사출 부품 | 6종 | INJ-코드 (범퍼쉘, 브라켓, 도어트림 등) |
| 원재료 | 6종 | RAW-코드 (PP, ABS, PA66-GF30, POM, PC+ABS, 마스터배치) |
| BOM 1단계 | 4개 | 완제품 → 사출부품 |
| BOM 2단계 | 6개 | 사출부품 → 원재료 (kg 단위) |
| 사출기 | 4대 | CC300 x2 (3000톤), CC200 x2 (2000톤) |
| 금형 | 6개 | 캐비티, 교체시간, 샷카운트 설정 |
| 사출기-금형 조합 | 8개 | 사이클타임, 불량율, 시간당능력 |
| 공급업체 | 3곳 | 한국폴리머, 대한수지, 컬러텍 |
| 구매가격 | 7건 | 원재료별 단가, 최소주문량, 리드타임 |
| 제품 원가 | 16건 | 전 제품 standard_price |
| 초기 재고 | 12건 | 사출부품 ~2일치, 원재료 ~5일치 |
| 수요 데이터 | ~20건 | 7일간 완제품 일별 수요 |
| 가동 일정 | ~28건 | 4대 x 7일 (주말 비가동, 수요일 정비) |
| 계획 설정 | 1건 | 안전재고 3.5일, 교대 8h/8h |

### 테스트 절차
1. 모듈 업그레이드 후 **생산계획 > 설정 > 샘플 데이터 생성** 실행
2. **생산계획 > 계획 실행** → 생성된 계획 클릭
3. `[계획 계산]` 버튼 클릭
4. 계획 라인 탭에서 결과 확인
5. `[일별 분석]` 버튼으로 차트 확인
6. `[확정 (MO 생성)]`으로 MO 생성 테스트

---

## 10. 의존성

```python
"depends": ["base", "mail", "mrp", "stock", "product"]
```

Odoo 표준 모듈만 의존합니다. Enterprise 기능 불필요.

---

## 11. PR 리뷰 체크리스트

### 파일 목록 (36개)

```
__init__.py, __manifest__.py
controllers/__init__.py, controllers/api.py
data/cron.xml, data/sequence.xml
models/__init__.py
models/mold.py
models/machine_mold_capability.py
models/machine_availability.py
models/planning_config.py
models/production_demand.py
models/planning_run.py          ← 메인 스케줄링 엔진 (~860줄)
models/planning_line.py
models/planning_daily_summary.py
models/product_planning.py
models/mrp_production.py
wizards/__init__.py
wizards/import_demand_wizard.py
wizards/generate_mo_wizard.py
wizards/generate_demo_wizard.py ← 샘플 데이터 생성 (~490줄)
wizards/import_demand_wizard_views.xml
wizards/generate_mo_wizard_views.xml
wizards/generate_demo_wizard_views.xml
views/mold_planning_views.xml
views/planning_config_views.xml
views/machine_mold_views.xml
views/machine_availability_views.xml
views/demand_views.xml
views/planning_run_views.xml
views/planning_line_views.xml
views/planning_daily_summary_views.xml
views/product_planning_views.xml
views/menu.xml
security/security.xml
security/ir.model.access.csv
```

### 리뷰 시 주의사항

1. **Odoo 18 호환**
   - 제품 타입: `type='consu'` + `is_storable=True` (product 타입 삭제됨)
   - workcenter: `default_capacity` (capacity 필드 삭제됨)
   - graph 뷰: `<graph type="line">` 문법

2. **보안**
   - 2개 그룹: `group_planning_user`, `group_planning_manager`
   - API: Bearer 토큰 인증 (`auth="bearer"`)
   - Oracle 비밀번호: `password=True` 필드

3. **성능**
   - 계획 계산: demand → BOM 전개 → 순수요 → 스케줄링 순차 처리
   - 대량 데이터 시 `create(vals_list)` 벌크 생성 사용
   - 일별 요약은 계획 계산 시 한번에 생성 (별도 조회 없음)

4. **확인 필요 항목**
   - [ ] 제품 카테고리 재고평가 설정 (Automated) → 자동분개 동작 확인
   - [ ] Oracle 연결 테스트 (운영 환경)
   - [ ] CSV 임포트 인코딩 (EUC-KR / UTF-8)
   - [ ] MO 생성 후 완료 시 원재료 자동 소비 확인

---

## 12. 커밋 히스토리 (주요)

| 커밋 | 내용 |
|------|------|
| a543f508 | 최초 모듈 생성 |
| 0975bb21 | Oracle Thick 모드 + 피벗 테이블 연동 |
| c50a17b5 | CSV 파일 업로드 + 가동시간 변수 |
| 03c94b93 | 교대근무, 가동일정, 안전재고 변수 |
| bfe89f90 | CSV 임포트 시 없는 제품 자동 생성 |
| 47eed8cb | 주간/야간 가용시간 Float 입력 변경 |
| 515fb81d | 완제품 → BOM → 사출부품 구조 재설계 |
| 08ddfa19 | 일별 생산계획 분석 차트 추가 |
| f2072bcd | 원재료 + 2단계 BOM 추가 |
| 2ba35456 | 초기 재고 자동 설정 |
| 389cbc4e | 공급업체, 구매가격, 제품 원가 |

---

## 13. 향후 개발 예정

- [ ] 제품 카테고리 자동 설정 (재고평가=Automated + 회계 계정 매핑)
- [ ] Go 미들웨어 확장: 중량 로봇 연동 API
- [ ] Go 미들웨어 확장: 바코드 로봇 연동 API
- [ ] Odoo 시리얼 업데이트 API (PUT /serial/:id → weight)
- [ ] 원재료 소요량 분석 (MRP 전개 기반 구매 제안)
- [ ] 생산 실적 대비 계획 달성율 대시보드
