# CLAUDE.md

> 이 파일은 Claude Code가 프로젝트 맥락을 빠르게 파악하기 위한 참조 문서입니다.

## 프로젝트 개요

자동차 부품 사출 성형 공장의 생산관리 시스템 (Odoo 18 Community 기반)

- **GitHub**: https://github.com/wilcoco/odoo
- **브랜치**: `18.0`
- **플랫폼**: Odoo 18 Community Edition

## 핵심 모듈

### 1. `addons_custom/injection_planning` — 사출 생산계획 (핵심)

자동차 부품 사출 성형 일별 생산계획 수립 모듈

**주요 기능:**
- BOM 전개 → 순수요 계산 → 사출기 배정 → MO 생성 자동화
- 안전재고(N근무일), 풀 캐퍼 생산, 금형교환 최소화
- Oracle 연동 수요 데이터 조회
- 일별 분석 차트 (재고/수요/생산/안전재고)

**핵심 파일:**
- `models/planning_run.py` — 스케줄링 엔진
- `models/planning_line.py` — 계획 라인
- `models/planning_config.py` — 설정 + Oracle 연결
- `PLANNING_SPEC.md` — 상세 기술 명세서

**데이터 모델:**
- `injection.mold` — 금형
- `injection.machine.mold.capability` — 사출기-금형 조합
- `injection.machine.availability` — 사출기 가동 일정
- `injection.planning.run` — 계획 실행
- `injection.planning.line` — 계획 라인
- `injection.production.demand` — 수요 데이터

### 2. `addons_custom/engel_injection` — 엥겔 사출기 연동

사출기 실시간 데이터 수집 및 모니터링

### 3. `addons_custom/supplier_portal_purchase` — 외주 자동발주 및 협력사 포탈

**주요 기능:**
- 생산계획 확정 시 외주 부품 자동 발주
- 협력사 포탈: 발주 확인, 납기/수량 응답, 승인 워크플로우
- 다단계 공급망 관리 (1차→2차→에스콘)
- 협력사 간 발주/수주 관리

**포탈 메뉴 구조:**
```
받은 발주 ▼
├── 에스콘에서 받은 발주 (purchase.order)
├── 다른 업체에서 받은 발주 (supplier.order)
└── 납품/출하 현황
보낸 발주 ▼
├── 다른 업체에 보낸 발주 (supplier.order)
└── 입고 현황
```

**테스트 URL:**
- `/supplier/portal?token=<협력사 포탈 접근 토큰>` — 토큰은 백오피스 구매 › 외주 관리 › 협력사 관리에서 복사
  (데모 토큰 `demo_token_*` 은 서버가 거부함. 발급 시 만료 180일 자동 설정)

**참고 문서:** `TEST_SCENARIO.md`

### 4. `addons_custom/iatf_*` — IATF 16949 품질경영 모듈 (31개)

감사, FMEA, SPC, PPAP, 측정장비 관리, 부적합 관리 등 자동차 산업 품질경영 표준 모듈

### 5. `engel-middleware/` — 엥겔 사출기 미들웨어 (Go)

사출기 PLC와 Odoo 간 데이터 브릿지 (untracked)

## 개발 컨벤션

### Odoo 모듈 구조
```
module_name/
├── models/          # 비즈니스 로직
├── views/           # XML 뷰 정의
├── wizards/         # 트랜지언트 모델 (위자드)
├── security/        # 접근 권한
├── data/            # 초기 데이터, cron
└── __manifest__.py  # 모듈 메타데이터
```

### 코드 스타일
- Python: Odoo 코딩 가이드라인 준수
- XML: Odoo 뷰 컨벤션
- 한글 주석/문서 사용

### 주의사항
- `capability.product_id`: related 필드 갱신 이슈 → `cap.product_id.id or cap.mold_id.product_id.id` 폴백 필수
- `stock.quant`: 직접 삭제 불가 → 수량 덮어쓰기 방식
- 생산수량: `math.ceil()` 정수 올림 필수
- 수요 기간: `plan_days + safety_stock_days` 이상 필요

## 자주 사용하는 명령어

```bash
# Odoo 서버 실행
./odoo-bin -c config.conf

# 모듈 업그레이드
./odoo-bin -c config.conf -u injection_planning

# engel-middleware 빌드 (Go)
cd engel-middleware && make build
```

## 최근 작업 이력

- **협력사 포탈 메뉴 개선** (2026-04): 받은발주/보낸발주 구분, 입고현황 추가
- **협력사 간 발주 기능** (2026-04): supplier.order 모델, 다단계 공급망
- **Odoo 18 호환성 수정**: type='consu' + is_storable, `<list>` 태그
- 사출 생산계획 스케줄링 알고리즘 구현 완료
- 풀 캐퍼 생산, 안전재고, 금형교환 최소화 로직
- 일별 분석 차트 (SQL View 언피벗)
