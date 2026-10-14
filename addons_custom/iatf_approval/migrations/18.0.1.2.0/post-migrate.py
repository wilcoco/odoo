"""Scope legacy visibility by today's target; never certify old approvals."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("SELECT id, res_model, res_id FROM iatf_approval_request WHERE company_id IS NULL")
    for request_id, model, res_id in cr.fetchall():
        if model not in env or 'company_id' not in env[model]._fields:
            continue  # Unknown provenance remains visible only to administrators.
        target = env[model].browse(res_id).exists()
        if target and target.company_id:
            cr.execute("UPDATE iatf_approval_request SET company_id = %s WHERE id = %s",
                       [target.company_id.id, request_id])
    # company_id is current access scope, not proof of historical company. The
    # default guard_version=0 stays unchanged for every old record.
    requests = env['iatf.approval.request'].search([])
    requests.invalidate_recordset(['company_id'])
    requests.modified(['company_id', 'guard_version'])
