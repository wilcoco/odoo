from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Apply the newly created singleton value to every company."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    settings = env.ref(
        "account_kr_plus_patch.account_kr_plus_settings_global"
    )
    settings._apply_global_rule()
