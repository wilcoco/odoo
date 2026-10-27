from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Migrate existing companies only. Do not create unsolicited standards elsewhere.
    for company in env['sq.standard'].search([]).mapped('company_id'):
        env['sq.standard'].with_company(company).action_load_catalog()
