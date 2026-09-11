import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.account_kr_reports.tools.report_adjust import (
    fix_sga_depreciation_types,
    fix_standard_pl_net_profit_tax,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """기본 손익계산서 보정 백필.

    1) 610006 감가상각비 등 61xxxx 의 expense_depreciation 유형 → expense
       (영업외비용 칸이 아니라 판관비로 집계)
    2) 화면에서 추가한 법인세 라인(TAX)을 당기순이익(NEP) 수식에서 차감
    멱등.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    changed = fix_sga_depreciation_types(env)
    tax_fixed = fix_standard_pl_net_profit_tax(env)
    _logger.info(
        "Standard P&L backfill: depreciation_types=%d, net_profit_tax=%s", len(changed), tax_fixed
    )
