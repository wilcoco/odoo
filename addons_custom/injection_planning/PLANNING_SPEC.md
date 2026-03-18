# 사출 생산계획 시스템 기술 명세서

> Odoo 18 Community 모듈 `injection_planning`
> 마지막 갱신: 2026-03-18 (v2 — 정수올림, 교체횟수 필드, capability 폴백 반영)

---

## 1. 시스템 개요

자동차 부품 사출 성형 공장의 일별 생산계획을 수립하는 Odoo 모듈이다.
완성품(차량 범퍼, 도어트림 등) 수요를 입력받아 BOM 전개 → 순수요 계산 → 사출기 배정 → MO 생성까지 자동화한다.

---

## 2. 데이터 모델

### 2.1 마스터 데이터

| 모델 | 설명 | 핵심 필드 |
|---|---|---|
| `injection.mold` | 금형 | `product_id`(생산 제품), `cavity_count`, `changeover_hours` |
| `injection.machine.mold.capability` | 사출기-금형 조합 | `workcenter_id`, `mold_id`, `cycle_time`(초), `defect_rate`(%), `initial_scrap`(개) |
| `injection.machine.availability` | 사출기 가동 일정 | `workcenter_id`, `date`, `day_shift_hours`, `night_shift_hours`, `last_mold_id` |
| `injection.planning.config` | 글로벌 설정 | `safety_stock_days`, 교대시간, 기본불량율, Oracle 연결 등 |
| `product.product` (확장) | 제품 | `max_inventory_qty`, `min_lot_size` |

### 2.2 핵심 계산 필드

```
hourly_capacity = (3600 / cycle_time) × cavity_count
daily_capacity = hourly_capacity × (day_shift_hours + night_shift_hours)
```

### 2.3 트랜잭션 데이터

| 모델 | 설명 |
|---|---|
| `injection.planning.run` | 계획 실행 (1회 = 1 레코드) |
| `injection.production.demand` | 수요 데이터 (완성품 × 날짜 × 수량) |
| `injection.planning.line` | 계획 라인 (사출기 × 날짜 × 제품 × 수량, `changeover_count` 0/1 피벗합계용) |
| `injection.planning.daily.summary` | 일별 요약 (차트용, 재고/수요/생산/안전재고) |

---

## 3. 스케줄링 알고리즘

### 3.1 전체 파이프라인

```
[1] BOM 전개 → [2] 순수요 계산 → [3] 사출기 배정 → [4] 계획라인 생성 → [5] 일별요약 생성
```

### 3.2 [1단계] BOM 전개 (`_explode_bom`)

- 입력: 완성품 수요 (86500-BS000EBB × 270개 / 2026-03-16)
- BOM에서 사출 부품 추출 (1레벨 전개만)
- 출력: `{(product_id, date_str): qty}` — 사출 부품 단위로 합산

```
예) 86500-BS000EBB 270개 + 86500-BS000SWP 150개
  → BOM 전개
  → INJ-BF-001(프론트범퍼쉘) 420개, INJ-BK-F01(브라켓) 840개
```

- **컬러 변종 합산**: 같은 사출 부품을 쓰는 완성품이 여러 개면 자연스럽게 합산
- BOM 없는 제품은 그 자체가 사출품으로 간주

### 3.3 [2단계] 순수요 계산 (`_calculate_net_requirements`)

#### 생산 원칙 (우선순위 순)

```
① 당일 부족 없음 (최우선): 소비 후 재고 < 0이면 반드시 생산
② 안전재고 확보: 향후 N 근무일 수요를 충당할 재고 유지
③ 풀 캐퍼 생산: 생산하는 날은 해당 제품 최고 사출기의 1일 최대 생산량으로 생산
④ 최대 재고 미초과: max_inventory_qty 이내로 제한
```

#### 핵심 변수

| 변수 | 설명 | 계산식 |
|---|---|---|
| `running_stock` | 실시간 재고 추적 (생산+소비 모두 반영) | 초기값 = `qty_available` |
| `after_consume` | 당일 수요 소비 후 재고 | `running_stock - required` |
| `future_demand` | 향후 N근무일 실제 수요 합 (=안전재고 목표) | 다음 N개 수요일의 수요 합산 |
| `need` | 생산 필요량 | `future_demand - after_consume` |
| `daily_cap` | 해당 제품 1일 풀 캐퍼 | `best_hourly_capacity × daily_hours` |

#### 알고리즘 흐름 (의사코드)

```python
for 각 (제품, 날짜) in 날짜순_정렬:
    if 날짜 > 계획종료일:
        continue  # 계획 기간 외 수요는 안전재고 참조만

    after_consume = running_stock[제품] - 당일수요

    # 향후 N근무일 실제 수요 합산 (주말 건너뜀)
    future_demand = sum(다음_N_근무일_수요)

    need = future_demand - after_consume

    # ① 당일 부족이면 반드시 생산
    if after_consume < 0:
        need = max(need, -after_consume)

    if need <= 0:
        running_stock[제품] = after_consume
        continue  # 생산 불필요

    # ② 풀 캐퍼로 생산
    produce = daily_cap  # (cap 없으면 need)

    # ③ 최대 재고 제한
    if max_inv > 0:
        produce = min(produce, max_inv - after_consume)

    # 당일 부족분은 최대 재고보다 우선
    if after_consume < 0:
        produce = max(produce, -after_consume)

    produce = ceil(produce)  # 정수 올림
    net[(제품, 날짜)] = produce
    running_stock[제품] = after_consume + produce
```

#### 안전재고 정의

- **정의**: 각 날짜에서 "향후 N근무일의 실제 수요 합"
- **N**: `injection.planning.config.safety_stock_days` (기본 3일)
- **근무일 기준**: 수요가 있는 날짜만 카운트 (주말/공휴일 자동 건너뜀)
- **목표**: `종료재고 ≥ 안전재고` (= 향후 N일분 수요를 커버하는 재고)

```
예) 3/16(월)의 안전재고
  = 3/17(화) 수요 + 3/18(수) 수요 + 3/19(목) 수요
  = 450 + 400 + 435 = 1,285
```

#### 풀 캐퍼 생산

- 생산 여부는 이진 결정 (produce or not)
- 생산하면 → 해당 제품의 **최고 효율 사출기-금형 조합 기준** 1일 최대 생산량
- 이유: 사출기를 반나절만 돌리는 것은 비효율 (세팅 비용, 금형 교환 등)

```
예) INJ-BF-001의 best capability:
    hourly_capacity = 65.5 (cycle_time=55초, cavity_count=1)
    daily_cap = 65.5 × 16h = 1,048개
```

### 3.4 [3단계] 사출기 배정 + 금형 교환 최소화 (`_schedule`)

#### 사출기 선택 기준

1. 해당 제품을 생산할 수 있는 `capability` 조회
2. `hourly_capacity`가 가장 높은 조합 선택

#### 금형 교환 최소화 전략

```
1. 전날 장착 금형 조회 (availability.last_mold_id)
2. 금형별 작업 그룹핑
3. 작업 순서 결정:
   a) 전날 금형과 같은 그룹 → 맨 앞 (교환 0회)
   b) 나머지는 총 작업량 많은 순 (큰 작업 먼저 → 교환 후 오래 사용)
4. 스케줄 종료 시 마지막 금형을 availability에 기록 (다음 계획용)
```

#### 수량 조정

| 항목 | 적용 시점 | 계산 |
|---|---|---|
| 불량율 보정 | 항상 | `ceil(demand / (1 - defect_rate/100))` |
| 초기 불량 | 금형 교환 시 | `+ initial_scrap` |
| 최소 로트 | 항상 | `max(adjusted, min_lot_size)` |

#### 시간 배치

- 가동일정(`machine.availability`)에서 해당 사출기/날짜의 가용 시간 조회
- 잔여 시간 부족 → 다음 가용일로 이동
- `start_time`, `end_time` 기록

### 3.5 [5단계] 일별 요약 (`_generate_daily_summary`)

- 계획 기간 **전체 날짜** (주말 포함) 생성
- 주말에도 종료재고, 안전재고 표시 (연속 그래프)
- `stock_end = stock_start + planned - demand`
- 안전재고: 향후 N근무일 수요 합 (주말 건너뛰기)

---

## 4. 주요 설정 파라미터

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `safety_stock_days` | 3 | 안전재고 일수 (향후 N근무일) |
| `day_shift_hours` | 8 | 주간 근무 시간 |
| `night_shift_hours` | 8 | 야간 근무 시간 |
| `day_shift_start` | 8.0 | 주간 시작 시각 |
| `default_changeover` | 2.0h | 금형 교체 시간 |
| `default_defect_rate` | 2.0% | 기본 불량율 |
| `default_initial_scrap` | 20 | 초기 불량 수량 |
| `default_min_lot_size` | 100 | 최소 로트 사이즈 |
| `planning_horizon` | 14일 | 자동 모드 계획 기간 |

---

## 5. 수요 데이터 소스

### 5.1 Oracle 연동

- 일별 수요: `T_ZM_PLN2` 테이블 (D00~D12 컬럼, 13일 피벗)
- 시간별 수요: `T_ZM_PLN1` 테이블 (5일×10시간 피벗)
- 커스텀 SQL 쿼리 지원

### 5.2 수동 입력

- 개별 수요 수동 입력 폼
- CSV 파일 업로드

### 5.3 수요 기간 규칙

- 계획 기간 + 추가 N일(=safety_stock_days) 수요를 입력해야 마지막 날짜의 안전재고 계산 가능
- 계획 기간 외 수요는 **안전재고 참조용**으로만 사용 (해당 날짜에 생산하지 않음)

---

## 6. 제약 조건 및 비즈니스 규칙

### 6.1 하드 제약 (반드시 충족)

1. **당일 부족 금지**: 소비 후 재고 < 0이면 반드시 생산
2. **기계 용량**: 1일 가용시간 × 시간당 생산능력 초과 불가
3. **금형-기계 호환**: capability에 등록된 조합만 사용
4. **정수 생산**: 생산 수량은 항상 정수 (ceil 올림)

### 6.2 소프트 제약 (가능한 충족)

1. **안전재고 유지**: 종료재고 ≥ 향후 N일 수요
2. **최대 재고 미초과**: `max_inventory_qty` 이내
3. **금형 교환 최소화**: 전날 금형 유지 우선
4. **최소 로트**: `min_lot_size` 이상 생산

### 6.3 우선순위 충돌 시

```
당일부족방지 > 안전재고 > 최대재고 > 금형교환최소화
```

- 당일 부족분은 최대 재고 한도보다 우선
- 안전재고 불충족 시 생산 트리거 (풀 캐퍼)
- 풀 캐퍼 생산이 최대 재고 초과 시 → 생산량 줄임 (단, 당일 부족분은 보장)

---

## 7. 리포트/뷰

| 메뉴 | 뷰 타입 | 설명 |
|---|---|---|
| 계획 실행 | form | 계획 생성/계산/MO생성 워크플로우 |
| 사출기 생산 계획 | list (날짜→사출기 그룹), pivot | 사출기별 일별 생산 품목/수량/교체횟수 |
| 일별 분석 | graph (line chart) | 4지표: 소요량, 생산량, 종료재고, 안전재고 |
| 수요 데이터 | list | 완성품 수요 원본 |

---

## 8. MO(제조 오더) 생성

- 계획 라인 → MO 1:1 생성
- BOM 자동 매칭 (product_id 또는 product_tmpl_id)
- `action_confirm()` 자동 호출 (확정 상태로)
- MO에 `planning_run_id` 역참조

---

## 9. 자동 모드 (Cron)

```
Oracle 수요 조회 → 계획 계산 → MO 생성 → 완료
```

- `injection.planning.config.auto_generate_mo = True` 시 활성화
- 계획 기간: 오늘 ~ 오늘 + `planning_horizon`일

---

## 10. 알려진 제한사항 및 개선 가능점

### 10.1 현재 방식의 한계

- **그리디 휴리스틱**: 전체 최적해 보장 안 됨 (날짜 순차 처리)
- **단일 기계 배정**: 제품별 최고 capacity 기계 1대만 사용 (복수 기계 분산 미지원)
- **1레벨 BOM 전개**: 사출 부품 → 원소재 전개는 미포함 (원소재 부족 미검증)
- **재작업/반품 미반영**: MO 완료 후 재고 변동은 다음 계획에 반영

### 10.2 코드 수정 시 주의사항

- **capability.product_id**: `related="mold_id.product_id"` (stored)가 갱신 안 될 수 있으므로, 코드에서 `cap.product_id.id or cap.mold_id.product_id.id`로 폴백 참조 필수
- **stock.quant**: Odoo에서 직접 삭제 불가 → 재고 초기화 시 수량 덮어쓰기 방식 사용
- **생산수량 정수**: `math.ceil()` 올림 처리 — 사출은 소수점 생산 불가
- **수요 기간**: `plan_days + safety_stock_days` 이상의 수요 제공 필요 (마지막 날 안전재고 계산용)
- **이전 MO 누적 재고**: MO 완료 시 사출 부품 재고가 누적되므로, 다음 계획 시 `qty_available`이 높아 생산 0이 나올 수 있음 (정상 동작)

### 10.3 정수계획(IP)으로 전환 시 구조

```
목적함수: min(금형교환횟수 × 교환비용 + 재고보유비용)

결정변수:
  x[p,m,d] = 제품 p를 기계 m에서 날짜 d에 생산하는 수량 (정수)
  y[m,d] = 기계 m이 날짜 d에 금형을 교환하는지 (0/1)

제약:
  ∀p,d: stock[p,d-1] + Σ_m x[p,m,d] - demand[p,d] ≥ safety_stock[p,d]
  ∀p,d: stock[p,d] ≤ max_inventory[p]
  ∀m,d: Σ_p (x[p,m,d] / capacity[p,m]) ≤ available_hours[m,d]
  x[p,m,d] = 0 if (p,m) not in capability
```

---

## 11. 파일 구조

```
injection_planning/
├── models/
│   ├── planning_run.py          # 핵심 스케줄링 엔진
│   ├── planning_line.py         # 계획 라인
│   ├── planning_config.py       # 설정 + Oracle 연결
│   ├── planning_daily_summary.py # 일별 요약 (차트 원본)
│   ├── planning_daily_chart.py  # SQL View 언피벗 (차트용)
│   ├── demand.py                # 수요 데이터
│   ├── mold.py                  # 금형
│   ├── machine_mold_capability.py # 사출기-금형 조합
│   ├── machine_availability.py  # 가동 일정
│   └── product_planning.py      # product.product 확장
├── views/
│   ├── planning_run_views.xml
│   ├── planning_line_views.xml  # 사출기 생산 계획 리포트 포함
│   ├── planning_daily_summary_views.xml
│   ├── demand_views.xml
│   ├── mold_planning_views.xml
│   ├── machine_mold_views.xml
│   ├── machine_availability_views.xml
│   ├── product_planning_views.xml
│   ├── planning_config_views.xml
│   └── menu.xml
├── wizards/
│   ├── generate_demo_wizard.py  # 샘플 데이터 생성
│   ├── generate_mo_wizard.py    # MO 생성 확인
│   └── import_demand_wizard.py  # CSV 수요 임포트
├── security/
│   ├── security.xml
│   └── ir.model.access.csv
└── data/
    ├── sequence.xml
    └── cron.xml
```

---

## 12. 용어 사전

| 용어 | 영문 | 설명 |
|---|---|---|
| 사출기 | Injection Machine | Odoo `mrp.workcenter` 확장 |
| 금형 | Mold | 사출 부품 형상 결정, 사출기에 장착 |
| 캐비티 | Cavity | 금형 내 성형 공간 수 (1회 사출 = 캐비티 수 만큼 생산) |
| 사이클타임 | Cycle Time | 1회 사출에 걸리는 시간 (초) |
| 금형 교환 | Changeover | 사출기에 장착된 금형을 다른 금형으로 교체 |
| 순수요 | Net Requirements | 총수요 - 현재고 - 안전재고 고려 후 실제 생산 필요량 |
| 풀 캐퍼 | Full Capacity | 해당 사출기의 1일 최대 생산 가능량 |
| BOM 전개 | BOM Explosion | 완성품 → 구성 부품 분해 |
| MO | Manufacturing Order | Odoo 제조 오더 |
| 안전재고 | Safety Stock | 향후 N근무일 수요를 충당할 수 있는 재고 수준 |
