# Views Summary

## 메뉴 구조
```
생산계획 (menu_injection_planning_root, seq=25)
├── 계획 실행 (seq=10) → action_planning_run
├── 일별 분석 (seq=15) → action_daily_chart  ← SQL View 차트
├── 수요 데이터 (seq=20) → action_demand
├── 사출기 가동 일정 (seq=25) → action_machine_availability
├── 마스터 데이터 (seq=30)
│   ├── 금형 관리 → action_injection_mold
│   └── 사출기-금형 조합 → action_machine_mold_capability
└── 설정 (seq=90)
    ├── Oracle 연결 / 기본값 → action_planning_config
    └── 샘플 데이터 생성 → action_generate_demo
```

---

## 뷰 파일별 상세

### planning_run_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| view_planning_run_search | search | name, 상태 필터 (초안/검토/확정) |
| view_planning_run_list | list | 번호, 기간, 수량, 교체수, MO수, 상태배지 |
| view_planning_run_form | form | header 버튼, stat 버튼(MO수/일별분석), notebook(수요/계획라인) |

**Form 버튼 (header)**:
- 수요 가져오기 (Oracle), 파일 업로드 (CSV), 수동 수요 추가
- 가동 일정 설정, 계획 계산 (confirm)
- 확정 (MO 생성), 취소, 초안으로

**Stat 버튼**:
- MO 수 → mrp.production 리스트
- 일별 분석 → injection.planning.daily.chart 그래프

### demand_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| view_demand_search | search | 제품, 날짜, 일별/시간별 필터, Oracle/수동 필터, 그룹(날짜/제품) |
| view_demand_list | list | editable=bottom, 날짜/제품/수량/타입/시간/소스/상태 |
| view_demand_form | form | 수동 입력용, hour는 hourly일 때만 표시 |

### planning_line_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| view_planning_line_list | list | 계획실행, 날짜, 사출기, 금형, 제품, 수량, 불량률, 교체여부, 총시간, MO, 상태 |
| action_planning_line | action | 계획 상세 (list) |

### planning_daily_summary_views.xml
**차트 모델 (daily.chart) — 그래프 전용**:
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| view_daily_chart_search | search | product_id, planning_run_id, searchpanel(view_types="graph,list") |
| view_daily_chart_graph | graph(line) | X: plan_date(day), groupBy: metric_type, measure: value |
| view_daily_chart_list | list | plan_date, product_id, metric_type, value |

**요약 모델 (daily.summary) — 리스트/피벗**:
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| view_daily_summary_search | search | product_id, 결품위기 필터, searchpanel(view_types="list") |
| view_daily_summary_pivot | pivot | 행: product, 열: date, 측정: 5개 |
| view_daily_summary_list | list | decoration-danger(결품위기), decoration-warning(근접) |

### mold_planning_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| form | form | 기본정보, 타수 관리, 상태 |
| list | list | 코드, 이름, 제품, 캐비티, 교체시간, 타수 |
| search | search | 코드, 상태 필터 |

### machine_mold_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| view_machine_mold_list | list (editable) | 사출기, 금형, 제품, 캐비티, 사이클, 불량률, 초기스크랩, 시간당능력 |

### machine_availability_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| list | list | 날짜, 사출기, 주간/야간 시간, 사유 |
| form | form | 사출기, 날짜, 시간 설정 |

### planning_config_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| form | form | 기본값(교체/불량/스크랩/로트), 교대(주간/야간), 안전재고 |

### product_planning_views.xml
| 뷰 | 타입 | 주요 요소 |
|-----|------|----------|
| form (inherit) | form | product.product에 max_inventory_qty, min_lot_size 추가 |

---

### 위자드 뷰

| 파일 | 위자드 | 주요 요소 |
|------|--------|----------|
| generate_mo_wizard_views.xml | MO 생성 확인 | 라인수/총수량/교체횟수 표시, 확인 버튼 |
| import_demand_wizard_views.xml | CSV 임포트 | 파일 업로드, Oracle교체/자동생성 옵션 |
| generate_demo_wizard_views.xml | 샘플 생성 | 시작일/기간/수요생성/가동일정 옵션 + action_generate_demo |

### REST API (controllers/api.py)

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| /api/v1/planning/mold | GET | 활성 금형 목록 |
| /api/v1/planning/capability | GET | 사출기-금형 조합 목록 |
| /api/v1/planning/run | GET | 최근 계획 실행 20건 |

인증: `auth="bearer"` (API 키)

---

## 보안 그룹
| 그룹 | XML ID | 설명 |
|------|--------|------|
| 생산계획 담당자 | group_planning_user | 조회 + 수요/계획 생성 |
| 생산계획 관리자 | group_planning_manager | 전체 CRUD + 설정 |

## 시퀀스
- `seq_planning_run`: PP-%(year)s%(month)s-NNNN

## 크론
- `ir_cron_auto_planning`: 매일 자동 실행 (기본 비활성)
