from . import models
from odoo import _
from odoo.exceptions import UserError


def uninstall_hook(env):
    """Shared approval evidence is immutable, including draft requests."""
    if env['iatf.audit'].search_count([('audit_type', '=', 'sq')]):
        raise UserError(_('SQ 평가서가 존재하여 결재 근거 보존을 위해 제거할 수 없습니다. '
                          '완전 원복은 적용 전 DB·첨부 백업과 코드를 함께 복원하십시오.'))
