# K-Guard 편입 인수인계 — account_kr_plus_patch

> 대상: `account_kr_guard` 관리 개발자.
> 이 문서 하나로 배경·구현·편입 절차·배포 순서까지 자기완결되도록 작성했습니다.
> 모듈 소스는 이 폴더 전체이며, 편입 후 이 모듈은 폐기(uninstall)됩니다.

## 1. 한 단락 요약

원화 환경에서 `.00` 이 남는 마지막 부류 — **`digits` 인자 없이 선언된
`fields.Float` 금액 필드**(코어 15개) — 의 자리수 소스를, 레지스트리 로드 완료
직후 실행되는 `_register_hook` 에서 화이트리스트 기반으로 재지정합니다.
새 소수점 정확도 항목 "KR Amount"(기본 0자리)를 신설해 금액이 이를 따르게 하고,
단가 성격 필드는 기존 "Product Price" 를 따르게 분리했습니다. 수량 필드는
의도적으로 제외했고 테스트로 고정했습니다.

## 2. 왜 설정만으로 안 되는가 (문제의 3계층)

| 자리수 소스 | 적용 대상 | 원화 대응 |
|---|---|---|
| `res.currency.rounding` (KRW=1) | `fields.Monetary` 전부 | 이미 해결 (통화 설정) |
| `decimal.precision` 레코드 | `digits="이름"` 인 Float | 이미 해결 (UI 조정 가능) |
| 소스 하드코딩 기본값 `(16, 2)` | `digits` **미지정** Float | **이 패치가 담당** |

세 번째 부류는 `Float.get_digits()` 가 `_digits=None` 일 때 무조건 (16, 2) 로
동작하므로, 코어 수정 없이는 어떤 설정으로도 못 바꿉니다. 계정과목 폼 '잔액'
버튼, 청구서 분석의 공급가액/합계/평균가/마진, 재고 평가액(value_svl) 등이
여기 해당합니다.

역사적 맥락: 운영 DB 에서 2026-03-05 에 관리자 계정이 "Product Price" 와
"Product Unit of Measure" 를 UI 에서 0으로 내려 금액 `.00` 을 눌러 잡았는데,
이 방식은 **수량 자리수까지 같이 죽이는** 부작용이 있었습니다 (BOM 원단위
소수점 소실 → `escon_uom_standard` 의 g 단위 정책이 그 뒷수습). 이 패치는
금액/수량 자리수 소스를 분리해 그 트레이드오프를 해소합니다. 수량 복원은
자매 모듈 `mrp_plus_patch` 가 담당합니다.

## 3. 구현 투어 (파일 3개)

### `data/decimal_precision.xml`
"KR Amount" = 0자리 신설. `noupdate="1"` — 설치 때 한 번 심고, 이후 회계팀이
UI 에서 바꾼 값은 모듈 업그레이드가 덮어쓰지 않습니다.

### `models/kr_amount_digits.py` (핵심, ~100줄)
- `account.move` 에 `_register_hook` 오버라이드. 이 훅은
  `odoo/modules/loading.py` STEP 9 (전 모듈 로드 완료 후 1회)와
  `Registry.setup_models` 의 `registry.ready` 분기(가동 중 모듈 설치 후)에서
  호출됩니다. 즉 **모든 애드온의 필드 셋업이 끝난 뒤** 실행되므로, 대상 모델의
  설치 여부·로드 순서와 무관하게 안전합니다.
- 하는 일은 `field._digits = "KR Amount"` (또는 `"Product Price"`) 재지정
  하나뿐입니다. `get_digits()` 가 이 값을 `decimal.precision` 조회로 풀어내므로
  표시(`fields_get`)와 캐시 반올림(`convert_to_cache`)이 함께 0자리가 됩니다.

**왜 `_inherit` 필드 재정의가 아닌가**: 대상이 6개 모듈·12개 모델에 흩어져
있어 재정의 방식은 (a) `sale`/`purchase`/`stock_account` 를 depends 로 강제
설치하게 되고, (b) 저장 필드는 `digits` 지정 시 컬럼 타입이 float8→numeric 으로
바뀌어 스키마 마이그레이션이 발생합니다. 훅 방식은 두 문제가 모두 없습니다.

### `tests/test_amount_digits.py`
화이트리스트 상수를 직접 import 해 검증 — 표를 고치면 테스트가 따라갑니다.

## 4. 안전장치 (설계 결정)

1. **화이트리스트**: `AMOUNT_FIELDS`/`UNIT_PRICE_FIELDS` 에 적힌 필드만.
   패턴 매칭 없음. 새 필드는 표에 추가해야 적용됩니다.
2. **수량 불가침**: `quantity`·`qty_*`·`product_uom_qty`·`quantity_svl` 제외,
   `test_quantity_fields_untouched` 로 고정.
3. **저장 필드 자동 제외**: `field.store and model._auto` 면 스킵 —
   표시 목적으로 컬럼 타입 변경 위험을 지지 않습니다 (위 (b) 방지의 이중 안전망).
4. **기존 `_digits` 존중**: 다른 모듈이 자리수를 선언한 필드는 건드리지 않음.
5. **끄기 스위치**: `ir.config_parameter` `account_kr_plus_patch.integer_amounts=0`
   + 재시작 (자리수는 레지스트리 구성 시 1회 적용이라 재시작 필요).

## 5. K-Guard 편입 절차

1. 파일 복사 (모듈 구조 그대로):
   - `models/kr_amount_digits.py` → `account_kr_guard/models/`
   - `data/decimal_precision.xml` → `account_kr_guard/data/`
   - `tests/test_amount_digits.py` → `account_kr_guard/tests/`
2. `account_kr_guard/models/__init__.py` 에 `from . import kr_amount_digits`,
   `tests/__init__.py` 생성/추가.
3. `__manifest__.py` `data` 에 `"data/decimal_precision.xml"` 추가, 버전 bump.
4. `kr_amount_digits.py` 의 `DISABLE_PARAM` 프리픽스를
   `account_kr_guard.integer_amounts` 로 변경 (파일 상단 docstring 의 파라미터
   안내도 함께).
5. 테스트: `--test-enable --test-tags=/account_kr_guard` — 4건 추가 통과 확인.

## 6. 배포 순서 — unique 제약 주의 (중요)

`decimal.precision.name` 에 unique 제약이 있어 "KR Amount" 레코드는 하나만
존재할 수 있습니다. 운영 DB 에 이 모듈이 이미 설치된 상태에서 편입본을
배포한다면 **반드시 이 순서**여야 합니다:

1. `account_kr_plus_patch` **uninstall** (레코드·파라미터가 함께 회수됨)
2. 편입된 `account_kr_guard` 로 upgrade (`-u account_kr_guard`)
3. 서버 재시작

한 번의 로드에서 "guard 가 새 레코드 생성 + plus_patch GC" 를 같이 하면
GC 가 로드 말미(`_process_end`)라 생성이 먼저 실행돼 unique 위반으로 죽습니다.
(운영에 plus_patch 가 아직 없다면 그냥 guard upgrade 만 하면 됩니다.)

## 7. 수동 검증 포인트 (설치/편입 후)

- 서버 로그에 `회계 금액 소수점 제거 적용: ...15개 필드` INFO 1줄
- 회계 > 계정과목 폼 '잔액' 스탯 버튼 — 소수점 없음
- 청구서 분석(account.invoice.report) 피벗 금액 — 소수점 없음
- 재고 > 제품 원가/평가액, 청구서 라인 수량 — 수량엔 소수점 유지
