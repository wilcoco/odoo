"""2.4.x → 2.5.0: 기 데이터 청구서의 빈 품목명(x_escon_item_name) 1회 백필."""

from odoo import SUPERUSER_ID, api

from odoo.addons.account_kr_plus_patch.item_backfill import backfill_legacy_item_names


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    backfill_legacy_item_names(env)
