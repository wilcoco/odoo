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
| 자재 발주(원재료·외주) | `injection_planning` / `supplier_portal_purchase` | 예비부품 쪽에서 PO 를 직접 만들지 말 것. 발주 경로가 둘로 갈라지면 이중 발주가 된다 |

## 세션 작업 규칙
1. 수요·정산·시리얼·결재처럼 "원장" 성격 데이터는 **만들지 말고 정본에 기록**한다.
2. 같은 모델에 두 모듈이 훅을 걸면 실행 순서·중복을 검토하고 이 파일에 기록한다.
3. 작업 단위별 브랜치 → PR. 다른 세션 활성 브랜치에 얹지 않는다.
4. 완료 전 검증: 원격 존재(ls-remote) + 테스트 그린 + (해당 시) 심볼 스캔.
5. **`-u` 는 미설치 모듈에 아무 일도 하지 않는다.** exit=0 을 검증으로 착각하지 말 것.
   검증 DB 에서 `ir_module_module.state` 를 먼저 확인하고, 미설치면 `-i` 로 설치한다.
6. **비저장 계산 필드 위에 `store=True` 를 얹지 않는다.** `product.qty_available`,
   `iatf.equipment.mtbf` 처럼 비저장인 값에 의존하면 Odoo 가 재계산 트리거를 걸지
   못해 값이 굳는다. 대신 비저장으로 두고 `search=` 메서드로 검색만 살린다.
   (검색뷰 filter/group_by 도 같은 제약 — `search=` 없으면 뷰 검증에서 실패하고,
   group_by 는 SQL 컬럼이 없어 아예 불가)
