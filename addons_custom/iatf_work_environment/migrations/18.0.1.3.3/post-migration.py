import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """이미 완료된 점검표에 '완료 이력' 을 세운다.

    새 필드 `was_done` 은 기본 False 다. 그대로 두면 **업그레이드 이전에 완료된 기록은
    '작성 중' 으로 되돌린 뒤 지울 수 있다** — 이 필드를 만든 이유가 바로 그 경로를
    막는 것인데, 과거 기록만 무방비로 남는다. (아스트라 재검토 2026-09-10 ②)

    현재 완료 상태인 것과, 취소됐지만 완료 판정 이력이 있는 것을 모두 표시한다.
    """
    cr.execute("""
        UPDATE iatf_check_record
           SET was_done = true
         WHERE COALESCE(was_done, false) = false
           AND (state = 'done' OR overall_result IN ('ok', 'issue'))
    """)
    _logger.info("점검 실적 %s 건에 완료 이력을 표시했습니다.", cr.rowcount)
