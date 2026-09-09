import logging

from odoo.addons.account_kr_reports.tools.approval_number import (
    approval_number_key,
    normalize_approval_number,
)

_logger = logging.getLogger(__name__)

SALES_TYPES = ("out_invoice", "out_refund")
TAX_DOCUMENT_TYPES = ("tax_invoice", "invoice")


def migrate(cr, version):
    """매출 전표의 ref에 담긴 승인번호를 정본이 비어 있을 때만 백필한다.

    1.4~1.5의 ref→정본 복사가 매입에만 적용되어, 이관으로 ref에 승인번호를
    받은 매출 청구서(2024 Q2 이관 72건 등)는 정본이 비어 있었다. 이미 다른
    전표가 쓰는 승인번호는 건너뛰고 로그로 남긴다. 멱등.
    """
    cr.execute("SELECT kr_approval_number_key FROM account_move "
               "WHERE COALESCE(kr_approval_number_key, '') != ''")
    taken = {row[0] for row in cr.fetchall()}
    cr.execute(
        """
        SELECT id, ref
          FROM account_move
         WHERE move_type IN %s
           AND COALESCE(kr_doc_type, 'tax_invoice') IN %s
           AND COALESCE(kr_approval_number, '') = ''
           AND COALESCE(ref, '') != ''
        """,
        (SALES_TYPES, TAX_DOCUMENT_TYPES),
    )
    updates, skipped = [], 0
    for move_id, ref in cr.fetchall():
        approval = normalize_approval_number(ref)
        if not approval:
            continue
        key = approval_number_key(approval)
        if key in taken:
            skipped += 1
            continue
        taken.add(key)
        updates.append((approval, key, move_id))
    if updates:
        cr.executemany(
            "UPDATE account_move SET kr_approval_number = %s, "
            "kr_approval_number_key = %s WHERE id = %s",
            updates,
        )
    _logger.info("KR sales approval backfill from ref: filled=%d, skipped_taken=%d",
                 len(updates), skipped)
