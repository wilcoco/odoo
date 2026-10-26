from odoo import api, models, _
from odoo.exceptions import ValidationError


class OpsApproverProfiles(models.Model):
    _inherit = 'cams.ops.policy'

    @api.model
    def _sync_approver_profiles(self):
        # Fixed profiles, never derive privileges from editable templates/domains.
        roles = {
            'quality': ['quality.group_quality_manager', 'cams_sq.group_sq_manager',
                        'iatf_audit.group_audit_manager', 'iatf_document_control.group_document_manager',
                        'iatf_change_management.group_change_management_manager',
                        'iatf_shipping_inspection.group_shipping_inspection_manager',
                        'iatf_process_inspection.group_process_inspection_manager',
                        'iatf_training.group_training_manager'],
            'settlement': ['account.group_account_manager', 'pumui_approval.group_pumui_manager'],
            'executive': ['pumui_approval.group_pumui_manager', 'escon_eapproval.group_eapproval_manager',
                          'iatf_audit.group_audit_manager', 'iatf_document_control.group_document_manager'],
        }
        for role, xmlids in roles.items():
            group = self.env.ref('cams_ops_policy.group_approver_' + role)
            grants = [self.env.ref(xmlid, raise_if_not_found=False) for xmlid in xmlids]
            group.write({'implied_ids': [(4, grant.id) for grant in grants if grant]})


class OpsApprovalTemplate(models.Model):
    _inherit = 'iatf.approval.template'

    def _ops_validate_approver_access(self):
        for template in self.filtered(lambda t: t.active and t.model_id):
            for line in template.line_ids.filtered(lambda l: l.approver_mode == 'user'):
                user = line.user_id
                if (not user.active or user.share or (template.company_id and template.company_id not in user.company_ids)
                        or not self.env[template.model_id.model].with_user(user).has_access('write')):
                    raise ValidationError(_('%(user)s: %(model)s 승인 역할 또는 적용 회사 권한이 없습니다. 템플릿 저장 전에 역할을 지정하십시오.') % {
                        'user': user.display_name, 'model': template.model_id.name})

    @api.constrains('active', 'model_id', 'company_id', 'line_ids')
    def _ops_check_template(self):
        self._ops_validate_approver_access()


class OpsApprovalTemplateLine(models.Model):
    _inherit = 'iatf.approval.template.line'

    @api.constrains('template_id', 'user_id', 'approver_mode')
    def _ops_check_line(self):
        self.mapped('template_id')._ops_validate_approver_access()
