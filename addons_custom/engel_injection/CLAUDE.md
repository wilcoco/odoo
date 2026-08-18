# engel_injection — LOT 자동 부여 범위 제한 수정

- **커밋**: `09a5d47` `[fix] engel_injection 수정` (2026-07-22)
- **변경 파일**: `models/mrp_production.py` (+6줄)
- (참고) 이 문서는 iatf_plugins 사본 은퇴 시 정본(addons_custom)으로 구조·이관됨.
  실측 확인: 로컬 DB 기준 mold_id 사용 0건·actual_mold_id만 지정된 escon 밖 MO 0건 —
  가드로 인한 기존 동작 변화 없음 (2026-07-23 검증).

## 문제 현상

`engel_injection` 모듈은 사출 MO 확정 시 `stock.lot`을 자동 생성해 `lot_producing_id`에 부여하기 위해 `mrp.production.action_confirm()`을 오버라이드하고 있다.

그런데 `action_confirm()`은 **모든 MO**가 통과하는 공통 경로다. 오버라이드 내부에 "이 MO가 사출 공정인지"를 판별하는 조건이 없었기 때문에, 모듈이 설치되어 있기만 하면 사출과 무관한 MO에도 LOT 규칙이 적용됐다.

즉, 아래 조건만 만족하면 공정 종류와 무관하게 LOT가 자동 생성·부여됐다:

- 제품 추적 방식이 `lot` 또는 `serial`
- `lot_producing_id`가 아직 비어 있음

### 타 공정에 미친 영향 (조립 공정)

- 조립 MO를 확정하는 순간 `LOT-YYYYMM-NNNN` 형식(`engel.production.lot` 시퀀스)의 LOT가 조립품에 부여됨.
- 조립 공정은 자체 LOT/시리얼 발행 체계를 따라야 하는데, 사출 모듈의 명명 규칙으로 만들어진 LOT가 선점되어 있어 정상 발행 흐름과 충돌.
- 사용자는 조립 MO에서 의도하지 않은 LOT가 이미 채워져 있는 것을 보게 되며, 스캔·추적 체계에 규칙 밖 LOT가 섞이게 됨.

## 원인

Odoo에서 `_inherit = "mrp.production"` 오버라이드는 모델 전역에 적용된다. 모듈 이름이 `engel_injection`이라고 해서 사출 MO에만 실행되는 것이 아니므로, **오버라이드 내부에서 적용 대상을 스스로 좁혀야 한다**. 이 가드가 누락되어 있었다.

## 수정 내용

`action_confirm()` 루프 선두에 사출 금형 가드를 추가했다:

```python
# Engel 사출 금형이 지정된 MO에만 이 모듈의 LOT 규칙을 적용한다.
# 모듈이 설치되어 있다는 이유만으로 조립 등 일반 MO에 LOT을
# 자동 부여하면 안 된다.
if not production.mold_id or production.mold_id.mold_type != "injection":
    continue
```

판별 기준은 `mold_id`(→ `iatf.mold`, `iatf_mold` 모듈)의 `mold_type` 필드다. `iatf.mold.mold_type`은 `injection`(사출 금형) 외에도 `press`, `die_casting`, `jig`, `fixture` 등을 가지므로, **사출 금형이 지정된 MO만** 이 모듈의 LOT 자동 생성 대상이 된다.

- `mold_id` 없음 (조립 등 일반 MO) → 건너뜀
- `mold_id`는 있으나 사출 금형이 아님 (프레스·지그 등) → 건너뜀
- 사출 금형 지정 MO → 기존 로직 진행

## 기존 가드와의 관계

이번 가드는 기존에 있던 제외 조건 **앞에** 추가된 것으로, 두 가드는 역할이 다르다:

| 가드 | 역할 |
|---|---|
| `mold_id.mold_type != "injection"` (신규) | 사출 외 **타 공정** MO를 제외 — 이번 수정 |
| `is_injection_mo` / `is_injection_part` (기존) | 사출 MO 중에서도 **escon_serial(14자리 규칙)이 발행을 담당하는** 사출품 MO를 제외. 2-tier 구조에서 계획 MO는 실물 LOT를 갖지 않고 단위 MO가 발행받음 |

결과적으로 이 모듈의 `LOT-YYYYMM-NNNN` 자동 부여는 "사출 금형이 지정되어 있으면서, escon_serial 발행 체계 밖에 있는" MO로만 한정된다.

## 확인 방법

1. 조립품(추적 `lot`) MO 생성 → 확정 → `lot_producing_id`가 비어 있어야 함 (수정 전에는 `LOT-YYYYMM-NNNN`이 자동 부여됨).
2. 사출 금형이 지정된 비(非)사출품 MO 확정 → 기존대로 LOT 자동 생성.
3. `is_injection_part` 사출품 MO 확정 → 여전히 건너뛰고 escon_serial이 발행.
