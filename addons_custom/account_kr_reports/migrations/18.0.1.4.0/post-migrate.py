import logging
from collections import defaultdict

from odoo.addons.account_kr_reports.tools.approval_number import (
    normalize_approval_number,
)

_logger = logging.getLogger(__name__)

STUDIO_FIELD = "x_escon_tax_approval_no"
INVOICE_TYPES = ("in_invoice", "in_refund", "out_invoice", "out_refund")
PURCHASE_TYPES = ("in_invoice", "in_refund")
TAX_DOCUMENT_TYPES = ("tax_invoice", "invoice")


def _has_column(cr, table, column):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s
           AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    """정본을 덮어쓰지 않고 과거 Studio/ref 승인번호를 안전하게 이관한다."""
    has_studio = _has_column(cr, "account_move", STUDIO_FIELD)
    studio_select = f", {STUDIO_FIELD}" if has_studio else ""

    cr.execute("SELECT id, kr_approval_number FROM account_move")
    existing = defaultdict(list)
    for move_id, value in cr.fetchall():
        if value and (normalized := normalize_approval_number(value)):
            existing[normalized].append(move_id)

    cr.execute(
        f"""
        SELECT id, move_type, kr_doc_type, ref{studio_select}
          FROM account_move
         WHERE move_type IN %s
           AND COALESCE(kr_approval_number, '') = ''
        """,
        (INVOICE_TYPES,),
    )

    candidates = defaultdict(list)
    invalid_studio = invalid_ref = source_mismatch = 0
    for row in cr.fetchall():
        move_id, move_type, document_type, ref = row[:4]
        studio_raw = row[4] if has_studio else False
        studio_value = normalize_approval_number(studio_raw)
        ref_value = (
            normalize_approval_number(ref)
            if move_type in PURCHASE_TYPES and document_type in TAX_DOCUMENT_TYPES
            else False
        )
        if studio_raw and not studio_value:
            invalid_studio += 1
        if (move_type in PURCHASE_TYPES and document_type in TAX_DOCUMENT_TYPES
                and ref and not ref_value):
            invalid_ref += 1
        if studio_value and ref_value and studio_value != ref_value:
            source_mismatch += 1
            continue
        value = studio_value or ref_value
        if value:
            candidates[value].append(move_id)

    updates = []
    duplicate_candidates = existing_conflicts = 0
    for value, move_ids in candidates.items():
        if len(move_ids) != 1:
            duplicate_candidates += len(move_ids)
            continue
        if existing.get(value):
            existing_conflicts += 1
            continue
        updates.append((value, move_ids[0]))

    if updates:
        cr.executemany(
            """
            UPDATE account_move
               SET kr_approval_number = %s
             WHERE id = %s
               AND COALESCE(kr_approval_number, '') = ''
            """,
            updates,
        )

    _logger.info(
        "KR approval compatibility: migrated=%d, studio_field=%s, "
        "invalid_studio=%d, invalid_ref=%d, source_mismatch=%d, "
        "duplicate_candidates=%d, existing_conflicts=%d; legacy values preserved",
        len(updates), has_studio, invalid_studio, invalid_ref, source_mismatch,
        duplicate_candidates, existing_conflicts,
    )
