"""기 데이터 품목명 백필 — x_escon_item_name 이 빈 청구서를 표준 라인 데이터로 채운다.

배경: 운영 DB 의 청구서 목록 뷰(account.view_invoice_tree, DB 에서 직접 수정됨)는
품목 컬럼으로 수동 필드 ``x_escon_item_name`` (account.move, Studio/수동 생성)을
쓴다. 초기 이관 때 이 필드를 채운 전표만 품목이 보이고, 이후 표준 경로로 만든
전표·이관에서 누락된 전표는 라인에 품목 정보가 있어도 목록에서 비어 보인다.

이 백필은 Odoo 기본 품목 데이터에서 계산되는 ``kr_product_names``
(라인의 product 표시명, 없으면 라인 적요)를 빈 x_escon_item_name 에 1회 복사한다.

- 수동 필드가 없는 DB(개발 등)에서는 조용히 건너뛴다.
- 이미 값이 있는 전표는 건드리지 않는다.
"""

import logging

_logger = logging.getLogger(__name__)

INVOICE_TYPES = ("out_invoice", "in_invoice", "out_refund", "in_refund")


def backfill_legacy_item_names(env):
    """빈 x_escon_item_name 을 kr_product_names 로 채운다. 채운 건수를 반환."""
    env.cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'account_move' AND column_name = 'x_escon_item_name'"
    )
    if not env.cr.fetchone():
        _logger.info("x_escon_item_name 컬럼이 없어 품목명 백필을 건너뜀 (이 DB 는 대상 아님)")
        return 0
    env.cr.execute(
        """
        UPDATE account_move
           SET x_escon_item_name = kr_product_names
         WHERE move_type IN %s
           AND COALESCE(x_escon_item_name, '') = ''
           AND COALESCE(kr_product_names, '') != ''
        """,
        (INVOICE_TYPES,),
    )
    count = env.cr.rowcount
    _logger.info("기 데이터 품목명 백필: %s건 (kr_product_names → x_escon_item_name)", count)
    return count
