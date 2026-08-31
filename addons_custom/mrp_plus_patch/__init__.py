"""수량 자리수(Product Unit of Measure) 1회 복원 로직.

'2로 강제'가 아니라 '설치/이번 버전 업그레이드 때 한 번, 2 미만이면 올림'이다.
이후 설정 > 기술 > 소수점 정확도에서 바꾼 값은 어느 경로로도 다시 건드리지
않는다 (post_init_hook 은 설치 때만, migration 은 해당 버전을 지날 때만 실행).
"""

import logging

_logger = logging.getLogger(__name__)

UOM_PRECISION = "Product Unit of Measure"
MIN_DIGITS = 2


def restore_uom_precision(env):
    """수량 자리수가 2 미만이면 2로 1회 복원 — 이미 2 이상이면 설정 존중(no-op)."""
    prec = env["decimal.precision"].search([("name", "=", UOM_PRECISION)], limit=1)
    if not prec:
        _logger.warning("소수점 정확도 '%s' 레코드가 없어 수량 자리수 복원을 건너뜀", UOM_PRECISION)
        return
    if prec.digits >= MIN_DIGITS:
        _logger.info("수량 자리수 %s자리 유지 — 기존 설정 존중(변경 없음)", prec.digits)
        return
    old = prec.digits
    prec.write({"digits": MIN_DIGITS})  # write 가 레지스트리 캐시(precision_get)도 비운다
    _logger.info("수량 자리수 복원: %s → %s (%s)", old, MIN_DIGITS, UOM_PRECISION)


def post_init_hook(env):
    restore_uom_precision(env)
