import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.account_kr_reports.tools.report_adjust import fix_non_operating_income_types

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """영업외수익(42xxxx) 계정 유형 백필 — income → income_other.

    기본 손익계산서가 이자수익·잡이익을 매출액으로 분류하던 원인. 한 번만 실행하는
    백필이다(이후 사용자가 의도적으로 바꾼 유형은 업그레이드 때 되돌리지 않는다). 멱등.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    changed = fix_non_operating_income_types(env)
    _logger.info("KR non-operating income account type backfill: changed=%d", len(changed))
