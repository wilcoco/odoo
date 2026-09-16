from odoo import api, models


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    @api.model
    def _approval_management_roles(self):
        return dict(super()._approval_management_roles(), **{
            'iatf.process.inspection': 'iatf_process_inspection.group_process_inspection_user',
        })
