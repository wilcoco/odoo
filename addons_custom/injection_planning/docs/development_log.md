# Development Log

---

## 2026-03-13 — 코드베이스 분석 + 문서화 + Best Practice 검토

### 작업 내용
1. 전체 코드베이스 정밀 분석 (11개 모델 + 3개 위자드 + 1개 컨트롤러)
2. docs/ 폴더 6개 문서 생성 및 정확한 코드 반영 업데이트
3. 위자드 뷰 설명 수정 (실제 생성 수량 반영)
4. 누락된 icon.png 생성 (static/description/)
5. models_summary.md 다수 오류 수정
6. views_summary.md 정확도 개선
7. Odoo Best Practice 관점 코드 리뷰

### 발견된 개선 가능 사항
- planning.config: res.config.settings 상속으로 싱글톤 패턴 개선 가능
- planning.line._compute_hours: search() 대신 related 필드 사용 권장
- _schedule: 루프 내 browse() 사전 캐시로 성능 개선 가능

### 변경 파일
- `docs/` 전체 (6개 파일 정밀 업데이트)
- `static/description/icon.png` (NEW)
- `wizards/generate_demo_wizard_views.xml`

---

## 2026-03-12 — SQL View 차트 + 자동 계획 계산

### 작업 내용
1. Odoo 18 graph 뷰 근본적 제약 발견 및 해결
   - graph 뷰는 measure 1개만 동시 표시 (archInfo.measure = 단수)
   - searchpanel은 기본적으로 kanban/list에서만 표시
2. SQL View 모델 `injection.planning.daily.chart` 생성
   - planning_daily_summary를 UNION ALL로 4배 언피벗
   - metric_type을 groupBy로 사용 → 4개 라인 동시 표시
3. searchpanel에 `view_types="graph,list"` 속성 추가
4. 샘플 위자드에서 자동 `action_calculate_plan()` 호출 추가
5. `search_default_product_id` 제거 (searchpanel과 충돌 방지)

### 변경 파일
- `models/planning_daily_chart.py` (NEW)
- `models/__init__.py`
- `models/planning_run.py`
- `views/planning_daily_summary_views.xml`
- `views/menu.xml`
- `security/ir.model.access.csv`
- `wizards/generate_demo_wizard.py`

### Git 커밋
- `09dd719a` 일별 분석: SQL View 언피벗 차트로 4개 라인 동시 표시
- `8bacc332` 샘플 위자드: 자동 계획 계산 + 일별 요약 데이터 생성

### 다음 작업
- 배포 후 그래프 동작 확인
- docs 폴더 생성 및 프로젝트 문서화

---

## 2026-03-12 — 이전 세션 작업 (요약)

### BOM 구조 재설계
- 컬러별 완제품이 같은 기준코드 → 같은 사출 부품 BOM 공유
- INJ-BK-001 → INJ-BK-F01 (프론트) + INJ-BK-R01 (리어) 분리
- 완제품 BOM 6개, 사출 부품 BOM 7개

### 샘플 위자드 개선
- BOM 삭제 후 재생성 (기존: skip if exists)
- 재고 항상 덮어쓰기 (기존: skip if qty > 0)
- 원재료, 공급업체, 원가, 초기 재고 추가

### 일별 분석 뷰 반복 수정
- group_by 제거 (X축 제품→날짜 문제)
- searchpanel 추가/수정 (icon 속성 제거 등)

### Git 커밋
- `e484fd87` 컬러 변종 BOM 분리 + 결품 위기 분석
- `4cce5f91` ~ `920c29bf` 그래프 뷰 반복 수정
- `092885f5` BOM 삭제 후 재생성 + 재고 강제 갱신
