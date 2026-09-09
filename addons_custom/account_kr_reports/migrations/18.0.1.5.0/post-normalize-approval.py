import logging
from collections import defaultdict

from odoo.addons.account_kr_reports.tools.approval_number import (
    approval_number_key,
    normalize_approval_number,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """충돌 없는 기존 승인번호만 정규화하고 논리 중복은 보존·보고한다."""
    cr.execute(
        """
        SELECT id, kr_approval_number, kr_origin_number
          FROM account_move
         WHERE COALESCE(kr_approval_number, '') != ''
            OR COALESCE(kr_origin_number, '') != ''
        """
    )
    rows = cr.fetchall()
    by_key = defaultdict(list)
    for move_id, approval, _origin in rows:
        if approval:
            by_key[approval_number_key(approval)].append((move_id, approval))

    approval_updates = []
    key_updates = []
    logical_duplicates = 0
    for key, records in by_key.items():
        key_updates.extend((key, move_id) for move_id, _value in records)
        if len(records) > 1:
            logical_duplicates += len(records)
            continue
        move_id, value = records[0]
        normalized = normalize_approval_number(value)
        if normalized and normalized != value:
            approval_updates.append((normalized, move_id))

    origin_updates = []
    for move_id, _approval, origin in rows:
        normalized = normalize_approval_number(origin)
        if normalized and normalized != origin:
            origin_updates.append((normalized, move_id))

    if approval_updates:
        cr.executemany(
            "UPDATE account_move SET kr_approval_number = %s WHERE id = %s",
            approval_updates,
        )
    if key_updates:
        # 1.4 이관이 SQL로 정본을 채운 뒤에도 새 저장 계산 키가 비어 있지 않도록
        # 명시적으로 백필한다. ORM 제약은 이후 신규/수정 논리 중복을 차단한다.
        cr.executemany(
            "UPDATE account_move SET kr_approval_number_key = %s WHERE id = %s",
            key_updates,
        )
    if origin_updates:
        cr.executemany(
            "UPDATE account_move SET kr_origin_number = %s WHERE id = %s",
            origin_updates,
        )
    _logger.info(
        "KR approval normalization: approval=%d, origin=%d, "
        "logical_duplicate_rows_preserved=%d",
        len(approval_updates), len(origin_updates), logical_duplicates,
    )
