"""1.0.x → 1.1.0 업그레이드 시 1회: 수량 자리수 복원 (2 미만일 때만).

신규 설치는 post_init_hook 이 같은 로직을 수행한다. 이 스크립트는 이 버전을
지나는 업그레이드에서 딱 한 번 실행되고 이후에는 다시 돌지 않는다.
"""

from odoo import SUPERUSER_ID, api

from odoo.addons.mrp_plus_patch import restore_uom_precision


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    restore_uom_precision(env)
