"""2026-09-27 사용자 결정 ①(잠정 적용): 이종검사 차단 방치 경보 한도(res_company.scan_block_alert_minutes)가
NULL 인 회사 행에 모듈 잠정 기본값 30분을 채운다. 0(명시적 끄기)과 이미 설정된 값은 건드리지 않는다.
동작: 차단이 30분 넘게 미해소로 서 있으면 제조오더에 경보 글 1회. 차단 자체는 이 값과 무관하게 항상 작동한다."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        "UPDATE res_company SET scan_block_alert_minutes = 30.0 "
        "WHERE scan_block_alert_minutes IS NULL RETURNING id"
    )
    rows = [row[0] for row in cr.fetchall()]
    _logger.info("scan_block_alert_minutes NULL -> 30.0 (provisional, decision 1 2026-09-27) companies=%s", rows)
