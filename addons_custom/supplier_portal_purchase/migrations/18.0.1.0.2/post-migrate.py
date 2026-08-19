import logging
from datetime import timedelta

from odoo import SUPERUSER_ID, api, fields

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """18.0.1.0.2 — 보안·정합성 마무리 데이터 보정.

    1. 포탈 사용 협력사 중 토큰 만료일이 비어 있는(무기한) 건에 오늘+180일 부여.
    2. '외주 관리' 메뉴가 외주 그룹으로 gating 되므로, 기존 구매 사용자/관리자에게 대응 외주 그룹을
       자동 부여 — 업그레이드 직후 아무도 메뉴를 잃지 않게 한다(이후 역할 분리는 관리자가 조정).
    """
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    # 1) 토큰 만료일 백필
    partners = env["res.partner"].search([
        ("is_supplier_portal", "=", True),
        ("supplier_portal_token", "!=", False),
        ("supplier_portal_token_expiry", "=", False),
    ])
    if partners:
        partners.write({"supplier_portal_token_expiry": fields.Date.today() + timedelta(days=180)})
        _logger.info("supplier_portal_purchase: 포탈 토큰 만료일(180일) 부여 — %d개 협력사: %s",
                     len(partners), ", ".join(partners.mapped("name")))

    # 2) 기존 구매 사용자 → 외주 그룹 자동 부여
    pairs = [
        ("purchase.group_purchase_manager", "supplier_portal_purchase.group_outsource_manager"),
        ("purchase.group_purchase_user", "supplier_portal_purchase.group_outsource_user"),
    ]
    for src_xmlid, dst_xmlid in pairs:
        src = env.ref(src_xmlid, raise_if_not_found=False)
        dst = env.ref(dst_xmlid, raise_if_not_found=False)
        if not src or not dst:
            continue
        users = src.users.filtered(lambda u: u.active and dst not in u.groups_id)
        if users:
            dst.write({"users": [(4, u.id) for u in users]})
            _logger.info("supplier_portal_purchase: %s -> %s 부여 — %d명",
                         src_xmlid, dst_xmlid, len(users))
