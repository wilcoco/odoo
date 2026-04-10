import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """production.demand 통합 - 기존 injection.production.demand 정리"""
    if not version:
        return

    _logger.info("Cleaning up old injection.production.demand...")

    # 기존 injection_production_demand 테이블 데이터 삭제 (테이블은 유지)
    cr.execute("""
        DELETE FROM injection_production_demand WHERE TRUE
    """)

    _logger.info("Old injection.production.demand data cleaned up")
