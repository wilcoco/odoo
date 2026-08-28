# 회계 금액 소수점 제거 패치 (account_kr_plus_patch)

원화(KRW) 환경에서 회계·구매·판매·재고평가 화면에 남는 `.00` 표시를 제거한다.
`account_kr_guard` 를 건드리지 않는 **별도 애드온**이며, 나중에 K-Guard 로 흡수해도
되도록 코드가 자기완결로 작성돼 있다 (아래 "K-Guard 로 옮길 때" 참조).

## 배경 — 왜 설정만으로는 안 되나

Odoo 의 금액 표시 자리수는 세 곳에서 결정되고, 앞의 두 곳은 이미 처리돼 있다.

| 자리수 소스 | 대상 | 상태 |
|---|---|---|
| `res.currency.rounding` (KRW=1 → 0자리) | `fields.Monetary` 전부 | ✅ 기본 설정으로 해결됨 |
| `decimal.precision` (설정 > 기술 > 소수점 정확도) | `digits="이름"` 으로 선언된 Float | ✅ UI 에서 조정 가능 |
| **소스에 박힌 기본값 `(16, 2)`** | `digits` **미지정** `fields.Float` | ❌ 설정 불가 → **이 모듈이 담당** |

세 번째 부류의 금액 필드는 코어 소스를 고치지 않는 한 자리수를 바꿀 방법이 없다.
계정과목 폼의 '잔액' 버튼(`account.account.current_balance`), 청구서 분석의
공급가액/합계/평균가/마진, 구매 청구 대사 금액, 재고 평가액(`value_svl`) 등이
여기에 해당해 늘 `1,234,567.00` 으로 떴다.

## 동작 방식

1. `data/decimal_precision.xml` — 소수점 정확도 항목 **"KR Amount" = 0자리** 신설
   (`noupdate`: 설치 때 한 번만 심고, 이후 UI 에서 바꾼 값은 업그레이드가 안 덮어씀).
2. `models/kr_amount_digits.py` — 레지스트리 로드 완료 직후 실행되는
   `_register_hook` 에서, 명시적 화이트리스트에 적힌 필드만 자리수 소스를 재지정:
   - **금액**(합계·잔액·평가액) → `"KR Amount"` (기본 0자리)
   - **단가**(할인적용단가 등) → 기존 `"Product Price"` 설정을 따르게 (금액/단가 분리 관리)

## 안전장치 (설계 결정)

- **화이트리스트 방식**: 패턴 매칭이 아니라 `AMOUNT_FIELDS` / `UNIT_PRICE_FIELDS`
  표에 적힌 필드만 만진다. 새 필드는 표에 추가해야 적용된다.
- **수량 제외**: `quantity`, `qty_*`, `product_uom_qty`, `quantity_svl` 등 수량 성격
  Float 는 표에서 의도적으로 뺐고, 회귀 테스트(`test_quantity_fields_untouched`)로
  고정했다. 수량 자리수는 `mrp_plus_patch` / "Product Unit of Measure" 설정이 담당.
- **저장(stored) 필드 자동 제외**: `digits` 를 넣으면 컬럼 타입이 `float8`→`numeric`
  으로 바뀌어 스키마 마이그레이션이 발생한다. 표시 목적으로 그 위험을 지지 않도록
  `field.store and model._auto` 인 필드는 건너뛴다 (compute/비저장/SQL뷰 필드만 대상).
- **`_digits` 가 이미 지정된 필드 존중**: 다른 모듈이 자리수를 선언했다면 건드리지 않는다.
- **미설치 모델 무시**: `sale`/`purchase`/`stock_account` 가 없으면 해당 항목만 조용히 스킵.
- **끄기 스위치**: 시스템 파라미터 `account_kr_plus_patch.integer_amounts = 0`
  + 서버 재시작 (자리수는 레지스트리 구성 시점에 한 번 적용되므로 재시작 필요).

## 적용 대상 필드 (18.0 기준 15개)

- `account.account.current_balance` — 계정과목 '잔액' 버튼
- `account.invoice.report` — `price_subtotal(_currency)`, `price_total`, `price_average`, `price_margin`, `inventory_value`
- `purchase.bill.union.amount`, `sale.order.amount_paid`
- `product.product.value_svl`, `stock.lot.value_svl`, `stock.valuation.layer.revaluation.current_value_svl`
- 단가 계열: `purchase.order.line.price_unit_discounted`, `purchase.bill.line.match.product_uom_price`, `sale.report.price_unit`

## K-Guard 로 옮길 때 (PR 체크리스트)

- `models/kr_amount_digits.py`, `data/decimal_precision.xml`, `tests/` 를 그대로 복사
- `DISABLE_PARAM` 의 모듈 프리픽스 변경, K-Guard `__manifest__.py` 의 `data` 에 XML 추가
- 이 모듈(`account_kr_plus_patch`)은 **먼저 제거(uninstall)** 해야 한다 —
  두 모듈이 같이 있으면 `decimal.precision` 의 `name` unique 제약("KR Amount" 중복)에 걸린다.

## 검증

`--test-enable --test-tags=/account_kr_plus_patch` — 4개 테스트:
정확도 레코드 존재 / 금액 필드 (16,0) / 단가 필드 = Product Price / 수량 필드 미변경.
