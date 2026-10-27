# 작업: 협력사 신고 재고 ↔ 납품 입고 연동(차감·재입력 요청)

- 저장소: `wilcoco/odoo`
- 브랜치: `feat/supplier-inventory-sync`
- 기준 브랜치/커밋: `18.0 / 4483d236c86b`
- 요청: 사용자 직접 결정(2026-10-19) "협력사의 재고는 협력사 입력 후 납품시 차감하되, 차감되고 나서 다시 생산하면 입력하라고 알려줘야 하는 구조" → 제안안 확정("제안된 답으로 다 확정한다"). 2026-10-26 동료 메모 "계속 진행하시면 됩니다".
- 담당: Claude (구현·서버 검증)
- 상태: 검토 요청

## 목적과 범위

- 해결할 문제: 협력사 포털 「내 재고 관리」(`supplier.inventory`)는 협력사가 신고한 숫자를 보관만 했다. 납품이 들어와도 숫자가 그대로라 사내 담당자는 협력사 재고를 믿을 수 없었고, 협력사는 언제 다시 입력해야 하는지 알 수 없었다(시뮬레이션 보고서 G-공급망 항목의 공백).
- 변경 범위: `supplier_portal_purchase`(재고 차감·요구량 비교·알림·메일·포털/사내 화면·시험), `scm_no_po_supply`(무발주 소요통보 잔량을 요구량에 합산·시험).
- 변경하지 않는 범위: 발주·ASN·입고 전표 흐름, 사내 `stock.quant`, 협력사 재고 입력 화면의 입력 규칙(`check_actor`, 수량 검증), 알림 목록 화면.

## 동작 규칙(확정안)

1. **차감 시점 = 당사 입고 확정.** 입고 전표(`stock.picking`, 입고 유형) `button_validate` 완료 시, 공급처가 포털 협력사(`is_supplier_portal`)인 완료 이동마다 제품 기본 단위로 환산한 수량을 그 협력사·제품의 신고 재고에서 뺀다. 0 아래로는 내려가지 않는다.
2. **멱등.** 이동 1건당 1회(`stock.move.supplier_inventory_deducted`). 신고 재고 행이 없으면 차감하지 않고 표시만 남겨, 나중에 행이 생겨도 과거 입고를 소급 차감하지 않는다.
3. **미입고 요구량** = 확정 발주(`purchase`/`done`) 잔량 Σ(`product_qty − qty_received`) + (`scm_no_po_supply` 설치 시) 발행 상태 무발주 통보 잔량 Σ(`quantity − received_quantity`). 모두 제품 기본 단위.
4. **부족 = 요구량 − 신고 재고 > 0 → 갱신 필요.** 차감 뒤 부족이면 포털 알림(`inventory_update` 유형)과 메일(`mail_template_supplier_inventory_update`)을 보낸다. 같은 품목의 안 읽은 요청이 남아 있으면 다시 보내지 않는다. 협력사가 수량을 다시 입력하면 바로 풀린다.
5. **화면.** 포털 첫 화면·내 재고 관리에 빨간 배너와 「당사 미입고 요구량 / 상태(갱신 필요·충분)」열. 사내 협력사 재고 목록에 요구량·부족·갱신 필요·최근 차감 열과 「갱신 필요」필터, 협력사별 묶기.

## 통합 영향

- 상태 전이: 입고 전표 완료 후 처리(super 이후). 차감·알림이 실패하면 입고도 롤백된다(같은 트랜잭션) — 신고 재고 행 쓰기는 sudo, 제약(`_check_scm_scope`)은 내부 사용자 기준으로 통과.
- 수량·재고: 사내 재고(`stock.quant`) 무관. 협력사 신고 재고(`supplier.inventory.quantity`)만 감소.
- LOT·시리얼, 납품·정산·전표: 없음.
- 품질 승인·기록 보호: 없음.
- 권한·회사 분리: 차감은 sudo 로 회사·협력사·제품을 좁혀 검색. 포털 배너는 토큰 협력사의 commercial partner + 현재 회사 범위만. 새 필드는 모두 읽기 전용·계산 필드라 포털 입력 가드(`write`) 영향 없음.

## 변경 내용

- `supplier_portal_purchase` 18.0.1.4.0 → **18.0.1.5.0**
  - `models/supplier_inventory_sync.py`(신규): `supplier.inventory` 계산 필드(`outstanding_qty`, `shortage_qty`, `needs_update`+검색, `portal_inventory_url`), 차감 기록 필드, `_outstanding_quantity`(확장점), `_deduct_for_receipt`, `_notify_update_needed`; `supplier.portal.notification.notification_type += inventory_update`; `stock.move.supplier_inventory_deducted`; `stock.picking.button_validate` 후처리
  - `data/inventory_mail_template.xml`(신규): 재고 갱신 요청 메일(`portal_notify_email` 우선)
  - `views/supplier_inventory_sync_views.xml`(신규): 사내 목록 열·검색 뷰·action 검색뷰, 포털 첫 화면 배너, 내 재고 관리 배너·열
  - `controllers/portal.py`: dashboard / my-inventory 에 `inventory_alerts`
  - `tests/test_inventory_sync.py`(신규 5건): 요구량 계산, 입고 차감·멱등·요구량 갱신, 부족 시 알림·메일 1회·재입력 해제, 0 하한·비포털 공급처 무관, 검색 필터
- `scm_no_po_supply` 18.0.1.1.0 → **18.0.1.2.0**
  - `models/supplier_inventory.py`(신규): `_outstanding_quantity` 에 발행 통보 잔량 합산
  - `tests/test_inventory_outstanding.py`(신규 1건)
- 설계 결정:
  - 차감 시점을 ASN 출하가 아니라 **당사 입고 확정**으로 둔 이유: 협력사가 ASN 을 만들지 않는 발주(일반 PO)도 같은 규칙을 타고, 실제로 들어온 수량만 빼기 위해서.
  - 요구량은 저장하지 않고 조회 때 계산(재고 행 수가 작고, 발주 상태가 바뀔 때마다 재계산 필요).
  - 알림 중복 방지는 "안 읽은 같은 품목 요청" 기준. 읽고 나서 또 부족하면 다음 입고 때 다시 보낸다.
- 데이터/호환성: 기존 신고 재고·알림 무변경. 설치 전 입고는 소급 차감하지 않는다. `stock.move` 에 Boolean 1개 추가(기본 False).

## 정본·미러 대응

- 정본 커밋 및 경로: `cffdb2e6b143` — `addons_custom/{supplier_portal_purchase,scm_no_po_supply}`
- 미러 커밋 및 경로: 미반영. 병합 후 `escon-odoo/odoo_gh/iatf_plugins/{supplier_portal_purchase,scm_no_po_supply}` 동기화 대상(미러 main 3e68b84 와 정본 기준 내용 동일 확인).
- 의도적 차이 또는 역반영 판정: 없음.

## 검증 증거

- DB/환경: 운영 서버 10.10.21.20 격리 시험 스택, DB `odoo18_auth_test`(2026-10-26 운영 덤프 재복원·중립화), 실행 코드 = 운영 런타임 + 이 브랜치 두 모듈 오버레이(`refresh-20261020/runtime-auth`), 운영 컨테이너 무변경
- 실행 명령(서버 `claude_auth_test.py`): `-u supplier_portal_purchase,scm_no_po_supply --test-enable --test-tags /supplier_portal_purchase,/scm_no_po_supply`
- 코드 커밋: `cffdb2e6b143`
- 결과 및 로그(서버 `/db/codex-testdb/odoo18-test-20261015/refresh-20261020/`):
  - 1차 `inv-sync-tests1.log`: 두 모듈 시험 **82건 실패 0·오류 0**(신규 6건 포함), 54초, 운영 무변경
  - 2차 `inv-sync-tests2.log`(포털 라우트 시험 추가 후): **83건 실패 0·오류 0**, 운영 무변경
  - 로그 경고는 기존 코드의 번역 컨텍스트 경고뿐(이번 변경과 무관)
- 미실행 검증과 이유: 화면(브라우저) 조작, 실제 메일 발송(시험 스택은 메일 서버 중립화).

## 배포·롤백

- 모듈 업그레이드/마이그레이션: `-u supplier_portal_purchase,scm_no_po_supply`. 마이그레이션 없음(필드 추가만).
- 재기동 및 확인: 구매 > 협력사 재고 목록에 「미입고 요구량·부족·갱신 필요」열이 보이는지; 포털 협력사 입고 1건 확정 후 신고 재고가 줄고, 부족하면 포털 알림이 생기는지.
- 롤백: 이전 커밋으로 `-u` 재실행. 추가 필드·알림 행은 남아도 무해.

## 작업 기록

- 2026-10-26: 구현·시험 작성(`cffdb2e6b143`), 서버 격리 시험 2회 통과(82→83건), 브랜치 푸시·PR 비교 링크 제시(병합·배포는 사용자 승인 대기).
