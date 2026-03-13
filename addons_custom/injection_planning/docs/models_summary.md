# Models Summary

## 모델 관계도
```
injection.planning.run (계획 실행)
├── One2many → injection.production.demand (수요)
├── One2many → injection.planning.line (계획 라인)
└── One2many → injection.planning.daily.summary (일별 요약)
                  └── SQL View → injection.planning.daily.chart (차트 데이터)

injection.mold (금형)
├── Many2one → product.product (생산 제품)
└── One2many → injection.machine.mold.capability (사출기-금형 조합)

injection.machine.mold.capability (사출기-금형 조합)
├── Many2one → mrp.workcenter (사출기)
└── Many2one → injection.mold (금형)

injection.machine.availability (가동 일정)
└── Many2one → mrp.workcenter (사출기)

injection.planning.config (설정) — singleton

product.product (확장)
├── injection_base_code (사출 기준코드)
├── max_inventory_qty (최대 재고)
└── min_lot_size (최소 로트)
```

---

## 1. injection.planning.run (계획 실행)
- **파일**: `models/planning_run.py`
- **상속**: `mail.thread`, `mail.activity.mixin`
- **순서**: `create_date desc`

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| name | Char | 계획 번호 (자동: PP-YYYYMM-NNNN) |
| plan_date_from | Date | 계획 시작일 |
| plan_date_to | Date | 계획 종료일 |
| state | Selection | draft/calculating/review/confirmed/done/cancelled |
| demand_ids | One2many | 수요 목록 |
| line_ids | One2many | 계획 라인 목록 |
| summary_ids | One2many | 일별 요약 목록 |
| total_planned_qty | Float | 총 계획 수량 (computed) |
| total_changeovers | Integer | 총 금형 교체 수 (computed) |
| mo_count | Integer | MO 수 (computed) |

### 핵심 메서드
| 메서드 | 설명 |
|--------|------|
| action_calculate_plan() | BOM 전개 + 스케줄링 + 일별 요약 생성 |
| action_fetch_demand() | Oracle에서 수요 로드 |
| action_import_demand_file() | CSV 파일 업로드 위자드 열기 |
| action_generate_availability() | 가동 일정 일괄 생성 |
| action_confirm_generate_mo() | MO 생성 확인 위자드 열기 |
| generate_manufacturing_orders() | 계획 라인 → MO 생성 |
| action_cancel() | 계획 취소 |
| action_reset_draft() | 초안으로 되돌리기 |
| action_view_mos() | 생성된 MO 보기 |
| action_view_daily_summary() | 일별 분석 차트 열기 (chart 모델) |
| _explode_bom() | 완제품 BOM → 사출 부품 소요량 |
| _calculate_net_requirements() | 순수요 = 수요 + 안전재고 - 재고 |
| _schedule() | 사출기 배정 + 수량 조정 + 스케줄링 |
| _generate_daily_summary() | 일별 요약 데이터 생성 |
| _cron_auto_planning() | 자동 모드 (cron) |

---

## 2. injection.production.demand (수요)
- **파일**: `models/production_demand.py`

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| planning_run_id | Many2one | 계획 실행 |
| product_id | Many2one | 제품 (완제품) |
| demand_date | Date | 수요일 |
| quantity | Float | 수량 |
| demand_type | Selection | daily/hourly |
| hour | Integer | 시간대 (0-23, hourly 전용) |
| source | Selection | oracle/manual |
| state | Selection | draft/planned/done |

---

## 3. injection.planning.line (계획 라인)
- **파일**: `models/planning_line.py`

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| planning_run_id | Many2one | 계획 실행 |
| sequence | Integer | 순서 |
| product_id | Many2one | 사출 부품 |
| workcenter_id | Many2one | 사출기 |
| mold_id | Many2one | 금형 |
| plan_date | Date | 계획일 |
| demand_qty | Float | 순수요 |
| planned_qty | Float | 계획 수량 (불량율+초기불량 반영) |
| defect_rate | Float | 적용 불량률 (%) |
| initial_scrap | Integer | 적용 초기 불량 |
| changeover_needed | Boolean | 금형 교체 필요 |
| changeover_hours | Float | 교체 시간 (h) |
| production_hours | Float | 생산 시간 (h, computed) |
| total_hours | Float | 총 소요 시간 (h, computed) |
| start_time | Datetime | 시작 예정 |
| end_time | Datetime | 종료 예정 |
| current_stock | Float | 현재 재고 |
| max_inventory | Float | 최대 재고 |
| mo_id | Many2one | 생성된 MO |
| state | Selection | draft/confirmed/done |

---

## 4. injection.mold (금형)
- **파일**: `models/mold.py`

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| name | Char | 금형명 |
| code | Char | 금형 코드 |
| product_id | Many2one | 생산 제품 (사출 부품) |
| cavity_count | Integer | 캐비티 수 |
| changeover_hours | Float | 금형 교체 시간 |
| guaranteed_shots | Integer | 보증 타수 |
| current_shots | Integer | 현재 타수 |
| state | Selection | active/maintenance/retired |

---

## 5. injection.machine.mold.capability (사출기-금형 조합)
- **파일**: `models/machine_mold_capability.py`

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| workcenter_id | Many2one | 사출기 (mrp.workcenter) |
| mold_id | Many2one | 금형 |
| product_id | Many2one | 생산 제품 (related, mold_id.product_id) |
| cavity_count | Integer | 캐비티 수 (related, mold_id.cavity_count) |
| cycle_time | Float | 사이클 타임 (초) |
| defect_rate | Float | 불량률 (%) |
| initial_scrap | Integer | 초기 스크랩 수 |
| hourly_capacity | Float | 시간당 생산능력 (computed: 3600/cycle × cavity) |
| active | Boolean | 활성 |

---

## 6. injection.machine.availability (가동 일정)
- **파일**: `models/machine_availability.py`

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| workcenter_id | Many2one | 사출기 |
| date | Date | 날짜 |
| day_shift_hours | Float | 주간 가동시간 |
| night_shift_hours | Float | 야간 가동시간 |
| available_hours | Float | 총 가용시간 (computed: day+night) |
| unavail_reason | Selection | breakdown/maintenance/no_order/holiday/other |
| notes | Text | 비고 |

---

## 7. injection.planning.config (설정)
- **파일**: `models/planning_config.py`
- **특징**: 싱글톤 패턴 (수동, 1개만 생성하여 사용)

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| oracle_host | Char | Oracle 호스트 (기본: 59.3.91.1) |
| oracle_port | Integer | Oracle 포트 (기본: 1521) |
| oracle_sid | Char | SID (기본: orcl) |
| oracle_user | Char | DB 사용자 |
| oracle_password | Char | DB 비밀번호 (password=True) |
| oracle_client_path | Char | Oracle Client 경로 (Thick 모드) |
| hourly_table | Char | 시간대별 테이블 (기본: T_ZM_PLN1) |
| daily_table | Char | 일자별 테이블 (기본: T_ZM_PLN2) |
| demand_query_daily | Text | 일별 수요 커스텀 SQL |
| demand_query_hourly | Text | 시간별 수요 커스텀 SQL |
| auto_generate_mo | Boolean | 자동 MO 생성 (cron) |
| planning_horizon | Integer | 계획 기간 (일, 기본: 14) |
| default_changeover | Float | 기본 금형 교체 시간 (시간) |
| default_defect_rate | Float | 기본 불량률 (%) |
| default_initial_scrap | Integer | 기본 초기 스크랩 (개) |
| default_min_lot_size | Integer | 기본 최소 로트 (개) |
| day_shift_hours | Float | 주간 근무시간 (기본: 8h) |
| night_shift_hours | Float | 야간 근무시간 (기본: 8h) |
| day_shift_start | Float | 주간 시작 시각 (기본: 8.0) |
| night_shift_start | Float | 야간 시작 시각 (기본: 20.0) |
| safety_stock_days | Float | 안전재고 일수 (기본: 3.5) |

### 메서드
| 메서드 | 설명 |
|--------|------|
| _get_oracle_connection() | Oracle DB 연결 객체 반환 (oracledb/cx_Oracle) |
| action_test_oracle_connection() | 연결 테스트 버튼 |

---

## 8. injection.planning.daily.summary (일별 요약)
- **파일**: `models/planning_daily_summary.py`

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| planning_run_id | Many2one | 계획 실행 |
| product_id | Many2one | 사출 부품 |
| plan_date | Date | 날짜 |
| demand_qty | Float | 소요량 |
| planned_qty | Float | 생산량 |
| safety_stock_qty | Float | 안전재고 |
| stock_start | Float | 시작 재고 |
| stock_end | Float | 종료 재고 |
| shortage_risk | Boolean | 결품 위기 (computed) |
| shortage_qty | Float | 부족 수량 (computed) |

---

## 9. injection.planning.daily.chart (차트 SQL View)
- **파일**: `models/planning_daily_chart.py`
- **특징**: `_auto = False` (SQL View)

### 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| planning_run_id | Many2one | 계획 실행 |
| product_id | Many2one | 사출 부품 |
| plan_date | Date | 날짜 |
| metric_type | Selection | 1_demand/2_planned/3_stock/4_safety |
| value | Float | 수량 |

---

## 10. product.product (확장)
- **파일**: `models/product_planning.py`
- **특징**: `_inherit = "product.product"`

### 추가 필드
| 필드명 | 타입 | 설명 |
|--------|------|------|
| injection_base_code | Char | 사출 기준코드 (컬러 무관 공통코드) |
| max_inventory_qty | Float | 최대 재고 수량 |
| min_lot_size | Float | 최소 로트 사이즈 |

---

## 11. mrp.production (확장)
- **파일**: `models/mrp_production.py`
- **특징**: `_inherit = "mrp.production"`
- **추가 필드**: `planning_run_id` (Many2one → injection.planning.run)

---

## 위자드 모델

### injection.generate.demo.wizard (샘플 생성)
- 완제품 6종, 사출부품 7종, 원재료 6종, BOM 13개
- 금형 7개, 사출기 4대, 조합 9개
- 수요 + 가동일정 + 자동 계획 계산

### injection.generate.mo.wizard (MO 생성 확인)
- 계획 라인 수, 총 수량, 교체 횟수 표시 후 확인

### injection.import.demand.wizard (CSV 임포트)
- CSV 파싱, 제품 자동 생성, Oracle 수요 교체 옵션
