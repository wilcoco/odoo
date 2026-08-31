# 세금계산서 승인번호 연동 계약

## 정본 필드

- 현재 세금계산서 승인번호: `account.move.kr_approval_number`
- 수정·취소분의 당초 승인번호: `account.move.kr_origin_number`
- 형식 독립 조회 키: `account.move.kr_approval_number_key`

업무 모듈은 Odoo 표준 `ref`나 과거 Studio 필드
`x_escon_tax_approval_no`를 승인번호로 조회하면 안 됩니다. `ref`는 공급업체의 자체
청구서 번호를 보존하는 내부 호환 필드이고, Studio 필드는 이관 후 폐기 대상입니다.

## 다른 모듈에서 찾는 방법

표시값의 하이픈·공백·대소문자 차이로 조회가 빠지지 않게 다음 공용 메서드를
사용합니다.

```python
move = self.env["account.move"]._kr_find_by_approval_number(
    external_approval_number,
    company=self.env.company,
    move_types=("in_invoice", "in_refund"),
    limit=1,
)
```

도메인이 꼭 필요하면 입력값을 `_kr_approval_key()`로 변환한 다음
`kr_approval_number_key`를 조회합니다. 전사 중복 검사처럼 레코드 규칙을 넘어야 하는
내부 관리 로직만 명시적으로 `sudo()`를 사용합니다.

## 보호 규칙

- 유효한 24자리 국세청 번호는 `YYYYMMDD-XXXXXXXX-XXXXXXXX`로 저장합니다.
- 하이픈·공백·대소문자만 다른 값도 같은 승인번호로 보아 신규 중복을 차단합니다.
- 값이 한 번 들어간 승인번호는 빈 값으로 삭제할 수 없습니다.
- 전기된 전표의 승인번호는 다른 값으로 변경할 수 없습니다. 필요한 경우 표준 회계
  절차에 따라 초안으로 되돌린 뒤 수정합니다.
- `kr_origin_number`도 변경 추적 대상으로 기록합니다.

## 현재 연동 지점

- 홈택스/스마트빌 세금계산서 반입 중복 차단
- 매출 세금계산서 승인번호 매칭
- 마감 체크리스트의 승인번호 누락 및 수정분 원본 전표 매칭 검사
- 품의서의 연결 청구서 승인번호 표시·검색
- 업로드 템플릿과 세금계산서 업무 화면

새 커스텀 모듈은 `account_kr_reports`에 의존하고 위 정본 필드·공용 메서드를
사용해야 합니다. 호환 필드명을 다시 도입하거나 `ref`에 역동기화하지 않습니다.

## Studio 호환 필드 폐기

모듈 업그레이드는 `x_escon_tax_approval_no`를 자동 삭제하지 않습니다. 회계 관리자가
`승인번호 필드 통합`에서 전사 데이터 이관 상태를 확인하고, 시스템 관리자가 화면,
서버 자동화, 사용자 필터, 레코드 규칙, 창 동작, 다른 사용자 정의 필드의 내부 참조를
모두 제거한 다음에만 명시적으로 삭제합니다. 외부 API·ETL·BI 연동은 Odoo DB에서
자동 검출할 수 없으므로 제거 확인란을 선택하기 전에 별도로 점검해야 합니다.
