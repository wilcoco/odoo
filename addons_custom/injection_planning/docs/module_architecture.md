# Module Architecture

## 모듈 목적
`injection_planning` 모듈은 사출 성형 공장의 생산계획 전 과정을 관리한다.

## 의존 모듈
```python
depends = ["base", "mail", "mrp", "stock", "product"]
```

## 데이터 흐름
```
① 수요 입력 (Oracle CSV / 수동)
   └→ injection.production.demand (완제품 기준)

② BOM 전개
   └→ 완제품 수요 × mrp.bom → 사출 부품별 소요량 집계

③ 스케줄링 알고리즘
   ├→ injection.machine.availability (사출기 가동시간)
   ├→ injection.machine.mold.capability (사출기-금형 조합)
   ├→ injection.mold (캐비티, 교체시간)
   └→ injection.planning.line (일별 사출기별 생산 스케줄)

④ 일별 분석
   ├→ injection.planning.daily.summary (와이드: 리스트/피벗)
   └→ injection.planning.daily.chart (언피벗 SQL View: 그래프)

⑤ MO 생성
   └→ mrp.production (Odoo 표준 제조 오더)
```

## 사용자 흐름
```
생산계획 메뉴
├── 계획 실행 (planning_run)
│   ├── [수요 가져오기] → Oracle CSV 업로드
│   ├── [계획 계산] → BOM 전개 + 스케줄링
│   ├── [일별 분석] → 그래프 차트 (4개 라인)
│   ├── [MO 생성] → 제조 오더 자동 생성
│   └── [확정] → 상태 변경
├── 수요 데이터
├── 일별 분석 (차트)
├── 사출기 가동 일정
├── 마스터 데이터
│   ├── 금형 관리
│   └── 사출기-금형 조합
└── 설정
    ├── Oracle 연결 / 기본값
    └── 샘플 데이터 생성
```

## 핵심 알고리즘

### BOM 전개 (_explode_bom)
- 완제품 수요를 BOM 1단계로 전개
- 같은 사출 부품이 여러 완제품에 포함될 경우 소요량 합산
- 예: 프론트 범퍼(블랙) 100개 + 프론트 범퍼(화이트) 50개 → INJ-BF-001 쉘 150개

### 순수요 계산 (_calculate_net_requirements)
- 순수요 = 수요 + 안전재고 - 현재재고
- 날짜순으로 누적 처리 (cumulative_produced 추적)
- 최대 재고 제한 적용

### 스케줄링 (_schedule)
- 제품별 가능한 사출기-금형 조합 → 시간당 생산능력 최대인 것 선택
- 사출기별 작업 수집 → 같은 금형 연속 배치 (금형 교체 최소화)
- 불량률 + 초기 불량 + 최소 로트 반영하여 수량 조정
- 가동 일정 기반 타임라인 스케줄링 (비가동일 건너뛰기)
- 남은 시간 부족 시 다음 가용일로 이동

### 일별 요약 (_generate_daily_summary)
- 계획 라인 집계 → 제품별 일별 소요/생산/재고 추이
- 안전재고 = 일평균수요 × 안전재고일수
- shortage_risk = 종료재고 < 안전재고

## SQL View 구조 (planning_daily_chart)
```sql
-- 와이드 포맷 (summary)를 4배 언피벗
SELECT id*4+0, ..., '1_demand', demand_qty FROM summary
UNION ALL
SELECT id*4+1, ..., '2_planned', planned_qty FROM summary
UNION ALL
SELECT id*4+2, ..., '3_stock', stock_end FROM summary
UNION ALL
SELECT id*4+3, ..., '4_safety', safety_stock_qty FROM summary
```
- Odoo 18 graph 뷰는 measure를 1개만 동시 표시 가능
- metric_type을 groupBy로 사용 → 4개 라인 동시 표시
- searchpanel `view_types="graph,list"` 로 graph에서도 사출 부품 선택 가능

---

## Odoo Best Practice 분석

### 잘 된 점
1. **모델 분리**: 각 도메인별 독립 모델 (금형/조합/가동/수요/계획/요약)
2. **_sql_constraints 활용**: 중복 방지 (사출기-금형, 사출기-날짜)
3. **mail.thread 상속**: 계획 실행/금형에 변경 추적 적용
4. **computed + store**: 성능과 검색 가능성 동시 확보
5. **ondelete="cascade"**: 상위 삭제 시 하위 자동 정리
6. **@api.model_create_multi**: Odoo 18 표준 생성 패턴
7. **SQL View 패턴**: _auto=False + init() + tools.drop_view_if_exists
8. **TransientModel**: 위자드에 적절한 모델 타입 사용
9. **보안 그룹 계층**: user -> manager implied_ids 체인
10. **company_id 필드**: 멀티 컴퍼니 대비

### 개선 가능 사항

#### 1. 설정 싱글톤 패턴 (우선순위: 낮음)
현재 `planning.config`는 수동 싱글톤 (1개만 생성하여 사용).
`res.config.settings` 상속으로 변경하면 설정 메뉴 통합 + 자동 싱글톤.
```python
# 현재: search([], limit=1) 으로 조회
# 개선: _inherit = "res.config.settings" + company_id 기반
```

#### 2. _compute_hours 성능 (우선순위: 중간)
planning_line._compute_hours에서 매 레코드마다 search() 호출.
대량 라인(수백 건) 시 N+1 쿼리 문제.
```python
# 현재: cap = self.env["...capability"].search([...], limit=1)
# 개선: capability_id Many2one 필드 추가하여 사전 연결
```

#### 3. _schedule 내 browse() (우선순위: 낮음)
루프 내 개별 `self.env["product.product"].browse(job["product_id"])` 호출.
```python
# 개선: 루프 전에 한번에 조회
# all_pids = set(j["product_id"] for jobs in machine_jobs.values() for j in jobs)
# products = self.env["product.product"].browse(list(all_pids))
# product_map = {p.id: p for p in products}
```

#### 4. BOM 전개 깊이 (우선순위: 낮음)
현재 BOM 1단계만 전개. 다단계 BOM이 필요한 경우:
```python
# mrp.bom._bom_explode() 활용 가능 (Odoo 표준 메서드)
```

#### 5. 배치 생성 최적화 (현재 양호)
대부분의 create() 호출이 vals_list 방식 (배치 생성) → 이미 최적화됨.

### 파일 구조 평가 (22개 파일)
```
injection_planning/           ✅ 표준 구조
├── __init__.py               ✅ models + wizards + controllers
├── __manifest__.py            ✅ 최소 의존, LGPL-3
├── models/ (12 파일)          ✅ 1파일 1모델 원칙
├── wizards/ (4 파일)          ✅ 위자드 분리
├── controllers/ (2 파일)      ✅ API 분리
├── views/ (10 파일)           ✅ 1모델 1뷰파일 원칙
├── security/ (2 파일)         ✅ 그룹 + ACL 분리
├── data/ (2 파일)             ✅ noupdate=1 적용
├── static/description/        ✅ 아이콘 포함
└── docs/ (6 파일)             ✅ 프로젝트 문서
```
