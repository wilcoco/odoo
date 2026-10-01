import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.account_kr_reports.tools.report_adjust import fix_kr_pl_formulas

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """손익계산서(KR) 수식 백필.

    l10n_kr_reports 의 영업이익 수식이 판관비를 더하고(KR_GRP + KR_EXP),
    법인세비용이 계정 63만 집계해 670001 법인세등이 빠져 있었다.
    예상 결함 수식과 같을 때만 고친다. 멱등.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    fixed = fix_kr_pl_formulas(env)
    _logger.info("KR P&L formula backfill: fixed=%d", fixed)
