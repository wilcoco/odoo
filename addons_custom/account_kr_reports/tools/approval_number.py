import re


APPROVAL_NUMBER_RE = re.compile(
    r"^\s*([0-9]{8})\s*-?\s*([0-9A-Za-z]{8})\s*-?\s*"
    r"([0-9A-Za-z]{8})\s*$"
)


def normalize_approval_number(value):
    """국세청 승인번호를 8-8-8 형식으로 정규화하고, 형식이 다르면 False를 반환한다."""
    match = APPROVAL_NUMBER_RE.fullmatch(str(value or ""))
    if not match:
        return False
    return "-".join(match.groups()).upper()


def approval_number_key(value):
    """형식 차이를 제거한 승인번호 조회 키를 반환한다.

    국세청 24자리 번호는 표준 8-8-8 값으로 통일한다. 과거 테스트·외부 연동에서
    쓰던 비표준 식별자는 대문자·앞뒤 공백만 정리해 기존 호환성을 유지한다.
    """
    normalized = normalize_approval_number(value)
    if normalized:
        return normalized
    fallback = str(value or "").strip().upper()
    return fallback or False
