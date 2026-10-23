from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError, UserError

DEFAULTS = {
    'bom_reactivate_old': 'warn', 'bom_delete_active': 'block', 'bom_log_immutable': True,
    'cr_self_review_block': True, 'cr_sequence_enforce': True,
    'mo_close_requires_good': True, 'planning_mo_qty_lock': True,
    'silo_reorder_po_state': 'draft', 'silo_setting_editor': 'worksite_manager',
    'scrap_requires_approval': True, 'leave_hr_skip_manager': False,
    'portal_token_mode': 'coexist', 'statement_link_days': 30,
}


class OpsPolicy(models.Model):
    _name = 'cams.ops.policy'
    _description = '회사 운영 정책'
    _inherit = ['mail.thread']
    _check_company_auto = True
    _rec_name = 'company_id'
    company_id = fields.Many2one('res.company', required=True, default=lambda self:self.env.company)
    change_reason = fields.Text('변경 사유', required=True, tracking=True)
    bom_reactivate_old = fields.Selection([('allow','허용'),('warn','경고 후 확인'),('block','차단')], string='구버전 BOM 재활성', default='warn', required=True, tracking=True)
    bom_delete_active = fields.Selection([('block','차단')], string='활성 BOM 삭제', default='block', required=True, tracking=True)
    bom_log_immutable = fields.Boolean('BOM 변경 이력 수정 차단',default=True, readonly=True)
    cr_self_review_block = fields.Boolean('4M 자기 검토·승인 차단', default=True, readonly=True)
    cr_sequence_enforce = fields.Boolean('4M 순서 강제', default=True, readonly=True)
    mo_close_requires_good = fields.Boolean('계획과 확정 양품 일치 후 종료',default=True,tracking=True)
    planning_mo_qty_lock = fields.Boolean('발행 계획 MO 수량 잠금', default=True,readonly=True)
    silo_reorder_po_state = fields.Selection([('draft','발주 초안'),('confirm','표준 구매 확인')],default='draft',required=True,tracking=True)
    silo_setting_editor = fields.Selection([('system','시스템 관리자'),('worksite_manager','사출 현장 관리자')],default='worksite_manager',required=True,tracking=True)
    scrap_requires_approval = fields.Boolean('폐기 전 품질 책임자 승인',default=True,tracking=True)
    leave_hr_skip_manager = fields.Boolean('휴가 관리자 1차 승인 생략 허용',default=False,tracking=True)
    portal_token_mode = fields.Selection([('coexist','로그인·토큰 공존'),('login','로그인 전용')],default='coexist',required=True,tracking=True)
    statement_link_days = fields.Integer('거래명세서 승인 링크 유효일',default=30,tracking=True)
    _sql_constraints = [('company_unique','unique(company_id)','회사당 운영 정책은 한 건입니다.')]

    @api.model
    def _value(self, company, key):
        """Private scalar read for guards; never broaden access to unrelated records."""
        if key not in DEFAULTS:
            raise ValueError(key)
        company.ensure_one()
        # Controllers validate their supplier/company boundary before calling.
        record = self.sudo().search([('company_id','=',company.id)],limit=1)
        return record[key] if record else DEFAULTS[key]

    @api.model
    def get(self, company_id):
        company = self.env['res.company'].browse(company_id)
        if company not in self.env.companies:
            raise AccessError(_('허용된 회사 정책만 조회하십시오.'))
        return self.search([('company_id','=',company.id)],limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('시스템 관리자만 정책을 등록할 수 있습니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'company_id' in vals:
            raise UserError(_('정책 회사는 변경할 수 없습니다.'))
        if set(vals)&set(DEFAULTS) and not (vals.get('change_reason') or '').strip():
            raise ValidationError(_('정책 변경 사유를 이번 저장에 입력하십시오.'))
        return super().write(vals)

    @api.constrains('statement_link_days','bom_log_immutable','change_reason',
                    'cr_self_review_block','cr_sequence_enforce','planning_mo_qty_lock')
    def _check_policy(self):
        for policy in self:
            if not 1 <= policy.statement_link_days <= 365 or not all(policy[k] for k in (
                    'bom_log_immutable','cr_self_review_block','cr_sequence_enforce','planning_mo_qty_lock')) or not (policy.change_reason or '').strip():
                raise ValidationError(_('유효기간 1~365일, 이력 불변, 변경 사유가 필요합니다.'))

    def unlink(self):
        if not self.env.context.get('module_uninstall'):
            raise UserError(_('정책은 삭제 대신 변경 사유를 남겨 개정하십시오.'))
        return super().unlink()


class OpsUser(models.Model):
    _inherit = 'res.users'

    @api.constrains('email','share','active')
    def _check_ops_email(self):
        for user in self:
            if not self.env.su and user.active and not user.share and not (user.email or '').strip():
                raise ValidationError(_('내부 활성 사용자는 이메일을 등록해야 합니다. 기존 누락 사용자의 업무 기록은 별도 로그 경로로 유지됩니다.'))
