"""품질 판정 공통 가드 — 빈값·기본값·초안을 판정/확정으로 쓰지 않기 위한 도우미.

478 묶음(결함 63건)의 공통 원칙을 한 곳에 모은다. 어느 모듈에서든
`from odoo.addons.iatf_document_control.models.quality_guards import is_blank`
로 가져다 쓴다. `iatf_document_control` 은 품질 모듈 전부가 의존한다.

규칙
- 사람이 적은 근거인지 판단할 때 파이썬 진리값(`if not value`)을 쓰지 않는다.
  공백만 있는 문자열과 빈 HTML 태그는 "적지 않은 것"이다.
- 숫자 0 과 False 는 서로 다르다. 0 은 유효한 측정값이므로 `is_blank` 는
  숫자를 받지 않는다(문자열·HTML 전용).
- 정책은 설정으로 둔다. `policy_enabled` 는 `ir.config_parameter` 를 읽고,
  설정이 없으면 권고 기본값을 쓴다. 과거 레코드를 소급해 바꾸지 않는다.
"""
import re

from odoo.tools import html2plaintext

# HTML 필드가 "비어 있음"으로 저장하는 대표 형태들.
_EMPTY_HTML = ("<p><br></p>", "<p><br/></p>", "<p></p>", "<p> </p>", "<br>", "<br/>")
_TAG = re.compile(r"<[^>]+>")


def is_blank(value):
    """사람이 적은 내용이 없으면 True.

    - None/False/'' → True
    - 공백·탭·줄바꿈만 → True
    - 빈 HTML 태그(`<p><br></p>` 등)만 → True
    - 숫자 0, 숫자 0.0 → **False**(0 은 유효한 값이다)
    """
    if value is None or value is False:
        return True
    if isinstance(value, (int, float)):
        return False
    text = str(value)
    if not text.strip():
        return True
    if text.strip().lower() in _EMPTY_HTML:
        return True
    if "<" in text and ">" in text:
        # Markup/HTML 필드: 태그를 걷어낸 실제 글자가 남는지 본다.
        plain = html2plaintext(text) if hasattr(html2plaintext, "__call__") else _TAG.sub("", text)
        return not (plain or "").replace("\xa0", " ").strip()
    return False


# `ir.config_parameter.get_param` 은 **키가 없을 때 `False` 를 돌려준다.**
# 이것을 "꺼짐" 으로 읽으면 설정을 한 번도 건드리지 않은 DB 에서 모든 가드가
# 조용히 비활성화된다(묶음 A 1차 CI 에서 8건이 "거부가 일어나지 않음" 으로 실패한
# 원인). 없음·빈값은 **권고 기본값**으로 떨어져야 한다.
_MISSING = (None, False, "")


def policy_raw(env, key):
    """설정값 원문. 키가 없으면 None(그 값이 `False` 여도 '없음' 과 구분)."""
    raw = env["ir.config_parameter"].sudo().get_param(key, default=None)
    if raw in _MISSING:
        return None
    text = str(raw).strip()
    return text or None


def policy_enabled(env, key, default=True):
    """설정값을 불리언으로 읽는다. **설정이 없으면 권고 기본값.**

    `ir.config_parameter` 키를 쓴다(회사 차원 없음 — 회사별 정책은 별도 범위).
    '0'/'false'/'no'/'off' 만 거짓으로 본다.
    """
    raw = policy_raw(env, key)
    if raw is None:
        return bool(default)
    return raw.lower() not in ("0", "false", "no", "off")


def policy_value(env, key, default):
    """선택지형 설정값을 문자열로 읽는다. 설정이 없으면 권고 기본값."""
    raw = policy_raw(env, key)
    return default if raw is None else raw


# ─────────────────────────────────────────────────────────────────────────────
# 내부 호출 표식 — 아무나 넘길 수 없는 값으로
#
# "확정·완료·취소는 버튼으로만" 이라는 가드를 context 플래그로 구현하면,
# **쓰기 권한이 있는 호출자가 그 플래그를 그대로 넘겨** 가드를 지나갈 수 있다.
# `with_context(env_check_completing=True)` 한 줄이면 되기 때문이다.
#
# 이 저장소의 결재 엔진은 이미 올바른 방식을 쓴다
# (`iatf_approval/models/approval_guard.py` — 모듈 전용 object 를 **동일성**으로
# 비교하고, 일반 참값을 넘겨도 막히는지 보는 시험까지 있다).
#
# 토큰은 이 모듈 안에만 있는 객체이고 `is` 로만 통과한다.
# `True`·`1`·`"yes"` 는 통과하지 못한다.
# ─────────────────────────────────────────────────────────────────────────────

_INTERNAL_TOKEN = object()


def internal_call(records, key):
    """가드를 지나갈 자격이 있는 **내부 호출**로 표시한다.

    버튼(액션 메서드)이 자기 검사를 모두 통과한 뒤에만 쓴다.
    """
    return records.with_context(**{key: _INTERNAL_TOKEN})


def is_internal_call(env, key):
    """그 표식이 **이 모듈이 발급한 것**인지. 일반 참값은 거짓이다."""
    return (env.context or {}).get(key) is _INTERNAL_TOKEN
