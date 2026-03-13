# Task List

## Phase 1 — 모델 + 기본 구조 ✅ 완료
- [x] 금형 모델 (injection.mold) — 자체 모델, IATF 의존 없음
- [x] 사출기-금형 조합 모델 (machine.mold.capability) — 8개 핵심 변수
- [x] 사출기 가동 일정 모델 (machine.availability) — 주간/야간 가동시간
- [x] 수요 모델 (production.demand) — Oracle/수동, daily/hourly
- [x] 계획 라인 모델 (planning.line) — 사출기별/일별 생산 스케줄
- [x] 계획 실행 모델 (planning.run) — 헤더 + 스케줄링 엔진
- [x] 계획 설정 모델 (planning.config) — Oracle 연결 + 글로벌 기본값
- [x] 제품 확장 (product.product: max_inventory, min_lot, injection_base_code)
- [x] MO 확장 (mrp.production: planning_run_id)
- [x] 일별 요약 모델 (planning.daily.summary) — 제품별 일별 집계
- [x] 차트 SQL View (planning.daily.chart) — 언피벗 그래프용

## Phase 2 — 비즈니스 로직 ✅ 완료
- [x] BOM 전개 알고리즘 (_explode_bom) — 완제품 -> 사출 부품 소요량
- [x] 순수요 계산 (_calculate_net_requirements) — 재고/안전재고 반영
- [x] 스케줄링 알고리즘 (_schedule) — 사출기 배정, 금형 교체 최소화
- [x] 일별 요약 생성 (_generate_daily_summary) — 재고 추이 계산
- [x] MO 자동 생성 (generate_manufacturing_orders)
- [x] CSV 수요 임포트 위자드 — 제품 자동 생성 옵션
- [x] 샘플 데이터 생성 위자드 — 6완제품/7사출부품/6원재료/13BOM/7금형/9조합

## Phase 3 — 뷰 + 분석 ✅ 완료
- [x] 모든 모델 form/list/search 뷰 (10개 XML 파일)
- [x] 메뉴 구조 (루트 -> 계획실행/일별분석/수요/마스터/설정)
- [x] 보안 그룹 + ACL (user/manager, 12개 모델)
- [x] 일별 요약 리스트/피벗 뷰 (결품 위기 표시)
- [x] SQL View 차트 모델 (언피벗, metric_type으로 4개 라인)
- [x] searchpanel view_types="graph,list" (그래프에서 제품 선택)
- [x] REST API (금형/조합/계획실행 조회, Bearer 인증)
- [x] 아이콘 파일 (static/description/icon.png)

## Phase 4 — 검증 및 문서화
- [x] 위자드 설명 업데이트 (정확한 수량 반영)
- [x] 문서화 (docs/ 폴더 6개 파일)
- [ ] **일별 분석 그래프 배포 후 동작 확인**
- [ ] 샘플 위자드 -> 자동 계획 계산 동작 확인

## Phase 5 — 확장 (계획)
- [ ] Go 미들웨어 확장: 중량 로봇 연동 API
- [ ] Go 미들웨어 확장: 바코드 로봇 연동 API
- [ ] Odoo 시리얼 업데이트 API (PUT /serial/:id -> weight)
- [ ] 입고 처리 흐름 설정 (발주 없이 입고만)
- [ ] 제품 카테고리 재고 평가 Automated 설정

## 알려진 이슈 및 개선 가능 사항
1. **일별 분석 그래프**: SQL View + searchpanel 조합이 Odoo 18에서 정상 동작하는지 배포 후 확인 필요
2. **설정 싱글톤 UX**: planning_config 액션에 res_id 미지정 -> 매번 새 폼 열림 (res.config.settings 상속으로 개선 가능)
3. **계획 라인 compute 성능**: _compute_hours에서 매번 search() 호출 -> 대량 데이터 시 성능 저하 가능 (related 필드로 개선)
4. **_schedule 성능**: 루프 내 개별 browse() 호출 -> 사전 캐시로 개선 가능
