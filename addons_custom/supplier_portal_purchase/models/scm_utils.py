"""Company/source boundaries shared by the supplier portal's own models."""
import math

from odoo import _
from odoo.exceptions import AccessError, ValidationError


def check_quantity(quantity, positive=False):
    if not math.isfinite(quantity) or quantity < 0 or (positive and quantity <= 0):
        raise ValidationError(_("수량은 유한한 양수여야 합니다.") if positive
                              else _("현재고 수량은 0 이상의 유한한 값이어야 합니다."))


def check_actor(record, partners):
    if not record.company_id:
        raise ValidationError(_("기존 자료의 회사 확인이 필요합니다. 담당자가 회사를 지정해야 합니다."))
    if record.company_id not in record.env.companies:
        raise AccessError(_("현재 허용 회사 밖의 공급 자료를 변경할 수 없습니다."))
    actor = record.env.user
    if not actor._is_public() and actor.has_group("base.group_user"):
        return
    partner = actor.partner_id.commercial_partner_id
    # A token route runs as public and is already authenticated by its controller;
    # it must pass the exact server-generated capability, never a JSON context flag.
    scope = record.env.context.get("_scm_portal_scope")
    if isinstance(scope, tuple) and len(scope) == 3 and scope[0] is _PORTAL_SCOPE:
        partner = record.env["res.partner"].browse(scope[1])
        if scope[2] != record.company_id.id:
            raise AccessError(_("포털 요청의 회사와 자료의 회사가 다릅니다."))
    elif actor._is_public():
        raise AccessError(_("인증된 협력사 요청이 필요합니다."))
    if partner not in partners.mapped("commercial_partner_id"):
        raise AccessError(_("다른 협력사의 공급 자료에 접근할 수 없습니다."))
    partner._scm_check_portal_company(record.company_id, user=actor)


_PORTAL_SCOPE = object()
