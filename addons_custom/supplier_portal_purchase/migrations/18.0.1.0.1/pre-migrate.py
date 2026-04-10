import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """production.demand 통합 전 기존 연결 테이블 정리"""
    if not version:
        return

    _logger.info("Cleaning up old demand relation tables...")

    # outsource_planning_demand_rel 테이블 정리
    cr.execute("""
        DROP TABLE IF EXISTS outsource_planning_demand_rel CASCADE
    """)

    # injection_planning_demand_rel 테이블 정리 (혹시 있으면)
    cr.execute("""
        DROP TABLE IF EXISTS injection_planning_demand_rel CASCADE
    """)

    _logger.info("Old demand relation tables cleaned up")
