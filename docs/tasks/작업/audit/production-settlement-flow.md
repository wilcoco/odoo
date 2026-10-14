# 작업: 입고·생산·정산·생산재고 원장 경계 인계

- 저장소: `wilcoco/odoo`
- 브랜치: `audit/production-settlement-flow`
- 기준 브랜치/커밋: `origin/18.0` / `17e9fac0eeeb7564e72e826caaf1865ba3b466a1`
- 정본 구현: `escon-odoo/odoo_gh` `fix/production-settlement-integrity`
- 구현 커밋: `541c5891e66ac9f97bbadcedeb465bc712b99f3c`
- 요청/검증일: 2026-09-16
- 상태: `완료`

## 범위와 저장소 결정

- 이 저장소에는 제품 코드를 넣지 않았다. 사용자가 요청한 교차 저장소 업무 경계·완료 조건·실행 증거 인계 문서만 유지한다.
- 정본 코드는 `odoo_gh`의 `injection_worksite 18.0.8.5.0`, `gh_vendor_settlement 18.0.2.2.0`에 구현했다.
- `injection_costing`은 실제 완료 stock move를 읽는 기존 책임을 유지하며 수정하지 않았다.
- 원부자재 관리 앱·메뉴·아이콘, 회사 운영 센터, 사출계획 최적화, Odoo 기본/엔터프라이즈 앱 접목은 이 작업에서 제외했다.

## 확정한 업무 경계

1. 원재료 매입 정산은 완료된 공급사 입고 `stock.move`를 양수, 원입고에 연결된 공급사 반품을 음수로 사용한다.
2. PO 발주수량과 SILO 적재·재적재 로그는 채무 확정 원천이 아니다. SILO 로그는 물류·LOT 감사 원장으로만 남는다.
3. 생산분 협력사 정산은 실제 양품수량 × 해당 MO BOM을 사용한다. BOM 단위와 부품 기준단위를 명시적으로 환산하고 `settle_by_ton` 원재료는 제외한다.
4. BOM raw move는 move UoM에서 제품 기준 UoM으로 바꿔 SILO FIFO를 계획하고, move line에는 다시 move UoM으로 환산한다. 따라서 500g stock move와 0.5kg SILO 차감이 같은 물량이다.
5. 완료 재처리·수량 정정·취소는 원본 행을 수정·삭제하지 않고 signed adjustment를 추가한다. 이미 청구된 행도 그대로 보존한다.
6. 구매/회계 잠금일 안쪽 원생산의 뒤늦은 보정은 원생산일을 보존하면서 현재일에 `마감 후 조정`으로 적립한다.
7. 공급사별 순조정액이 음수면 매입계산서가 아니라 공급사 환불(`in_refund`)을 만든다.

## 완료 조건과 실제 결과

| 조건 | 결과 |
|---|---|
| 공급사 입고와 내부 SILO 재적재 분리 | 입고 3,000kg, 내부 적재로그 6,000kg이어도 정산 3,000kg |
| 공급사 반품 | 200kg 반품 후 순정산 2.8톤, 입고·반품 move 2건 역추적 |
| 계획량 대신 실제 양품 | 계획 100/실적 2 기준으로 정산 생성 |
| BOM UoM | 1 dozen/개 × 양품 2개 = 24 Units |
| 재처리·취소 | 동일 재호출 no-op, 2→3개는 +12 Units, 취소는 음수 adjustment |
| 마감 후 조정 | 원생산일 보존, 잠금일 조정은 현재 반영일과 감사 플래그 기록 |
| 생산 재고 | 복제 DB MO `WH/MO/01390` 완료, 완제품 2 Units |
| BOM/SILO 대사 | stock move 500g = SILO 차감 0.5kg |

## WSL 복제·검증·운영 반영

- 원 DB: `esconodoo202609`
- 복제 DB: `esconodoo202609_settlement_test`
- PostgreSQL: 17 / port 5433 / owner `odoouser`
- 복제 방법: 원 DB online dump/restore 후 filestore를 별도 복사했다. 하드링크는 사용하지 않았다.
- 검증 addons 경로: 작업 worktree → `/opt/plugins/iatf_plugins` → `/opt/odoo/addons`
- 최종 회귀 명령의 핵심:

```text
odoo-bin -d esconodoo202609_settlement_test \
  -u injection_worksite,gh_vendor_settlement \
  --test-enable \
  --test-tags=/gh_vendor_settlement,/injection_worksite:TestTonSettlementGuard,/injection_worksite:TestSiloUomIntegrity \
  --workers=0 --max-cron-threads=0 --stop-after-init
```

- 최종 회귀: 16건, `0 failed / 0 errors`.
- 영구 E2E 스크립트: `scripts/verify_production_settlement_e2e.py`.
- E2E 식별자: `20260916000911`.
- E2E 결과: 정산 2.8톤, 원천 2건, 완제품 2개, 생산분 정산 24 Units, SILO/stock move 각각 0.5kg.
- 기존 DB 업그레이드:

```text
odoo-bin -d esconodoo202609 \
  -u injection_worksite,gh_vendor_settlement \
  --workers=0 --max-cron-threads=0 --stop-after-init
```

- 설치 버전: `injection_worksite 18.0.8.5.0`, `gh_vendor_settlement 18.0.2.2.0`.
- 서비스: `odoo.service active`, `/web/login?db=esconodoo202609` HTTP 200.

## 기존 데이터 마이그레이션·감사 목록

- 생산분 정산 5건은 기존 수량·단가·상태·청구서 연결을 변경하지 않고 `event_key`, BOM/UoM 스냅샷과 `legacy-migrated-planned-quantity` 사유를 채웠다.
- 5건 모두 고유 BOM 라인에 연결됐고 모호한 행은 0건이다.
- 기존 원재료 월정산 2건은 모두 draft다. 확정 정산 중 원천 미연결 행은 0건이다.
- 입고문서/PO 연결이 완전하지 않은 SILO 적재로그 3건은 자동 금융 원천으로 전환하지 않았다.

| 유형 | 실제 항목 |
|---|---|
| 생산분 원장 | IDs `1..5`; `WH/MO/00364`, `WH/MO/00685`, `WH/MO/00686`; 1 draft, 4 billed |
| 수동 판정 SILO 로그 | IDs `1,2,3`; 각 1,000kg; 2026-07-07/22/28; stock move는 있으나 picking/PO 없음 |
| 원재료 정산 | ID 1 `RMS/2026/0001` draft 1 line, ID 2 `TEST-톤정산2` draft 0 line |

재감사 SQL:

```sql
SELECT id, load_date, qty, stock_move_id, picking_id, purchase_order_id
FROM injection_silo_load_log
WHERE stock_move_id IS NULL OR picking_id IS NULL OR purchase_order_id IS NULL;

SELECT id, production_id, qty, state, event_key, source_key, reason
FROM vendor_mrp_accrual
ORDER BY id;
```

## 미검증·후속

- 현장 실물·회계 담당자의 사용자 인수시험과 실제 공급사 계산서 전송/전표 게시는 수행하지 않았다. 생성 검증은 draft 문서까지다.
- `injection_worksite` 전체 150건 실행에서 이번 정산 테스트는 통과했으나 기존 API key 격리, 호기 번호, bus cursor 관련 11건이 별도로 실패했다. 최종 범위 회귀 16건에는 이 독립 결함을 섞지 않았다.
- `odoo_gh` 브랜치와 이 인계 브랜치는 로컬에 유지한다. push/PR은 사용자가 수행한다.
