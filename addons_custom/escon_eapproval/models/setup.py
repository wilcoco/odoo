"""Odoo 기본 전자결재(Approvals)·휴가 유형 셋팅 자동화 + 표준 설정 거버넌스.

원칙 (회사 결정 사항)
1. 전자결재 요청 유형·휴가 유형의 "구조 설정"(필드 필수 여부, 결재 방식, 증빙,
   문서번호 등)은 이 파일의 스펙(CATEGORY_SPECS / LEAVE_TYPE_SPECS)이 정본이다.
2. 모듈 설치/업그레이드 때마다 apply_odoo_defaults() 가 스펙대로 강제 정합한다
   (data/approval_setup.xml 의 <function> 호출, 멱등). UI 에서 바꿔도 되돌아온다.
3. 보호 필드는 UI 수정 자체를 차단한다(아래 write/unlink 가드). 변경이 필요하면
   이 파일의 스펙과 data XML 을 함께 수정하고 모듈을 업그레이드한다.
4. 결재자 지정(approver_ids)·설명·이미지·정렬 등 운영 재량 항목은 막지 않는다.

수동 재적용: 에스콘 전자결재 > 설정 > "Odoo 전자결재 기본 셋팅 재적용"
"""

import logging

from odoo import _, api, models
from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# 셋업 루틴이 보호 필드를 쓸 때 사용하는 컨텍스트 플래그
SETUP_CTX = "escon_eapproval_setup"

# Odoo Approvals 기본 유형 — 전부 보관(비활성) 처리. 데이터 삭제는 하지 않는다.
DEFAULT_CATEGORY_XMLIDS = [
    "approvals.approval_category_data_business_trip",
    "approvals.approval_category_data_borrow_items",
    "approvals.approval_category_data_general_approval",
    "approvals.approval_category_data_contract_approval",
    "approvals.approval_category_data_payment_application",
    "approvals.approval_category_data_car_rental_application",
    "approvals.approval_category_data_job_referral_award",
    "approvals.approval_category_data_procurement",
    "approvals_purchase.approval_category_data_rfq",
]

# ── 전자결재 요청 유형 표준 스펙 (data/approval_category_data.xml 과 일치 유지) ──
_CATEGORY_BASE = {
    "active": True,
    "approval_minimum": 1,
    "approver_sequence": True,
    "manager_approval": "approver",
    "automated_sequence": True,
    "approval_type": False,
    "requirer_document": "optional",
    "has_date": "no", "has_period": "no", "has_quantity": "no", "has_amount": "no",
    "has_reference": "no", "has_partner": "no", "has_payment_method": "no",
    "has_location": "no", "has_product": "no",
}

CATEGORY_SPECS = {
    "escon_eapproval.category_general": dict(
        _CATEGORY_BASE, name="일반 결재", sequence_code="GEN",
        has_reference="optional"),
    "escon_eapproval.category_expense": dict(
        _CATEGORY_BASE, name="경비청구서", sequence_code="EXP",
        has_date="required", has_amount="required", has_payment_method="optional",
        has_partner="optional", requirer_document="required"),
    "escon_eapproval.category_trip": dict(
        _CATEGORY_BASE, name="출장", sequence_code="TRIP",
        has_period="required", has_location="required", has_partner="optional",
        has_amount="optional"),
    "escon_eapproval.category_car": dict(
        _CATEGORY_BASE, name="자동차 대여", sequence_code="CAR",
        has_period="required", has_location="optional"),
    "escon_eapproval.category_gate": dict(
        _CATEGORY_BASE, name="출입신청", sequence_code="GATE",
        has_period="required", has_partner="optional", has_location="optional"),
    "escon_eapproval.category_rfq": dict(
        _CATEGORY_BASE, name="견적 요청서 (RFQ)", sequence_code="RFQ",
        approval_type="purchase", has_product="required"),
}

# UI 수정 차단 대상(구조 설정). 운영 재량: description/image/sequence/approver_ids 등
PROTECTED_CATEGORY_FIELDS = set(_CATEGORY_BASE) | {"name", "sequence_code"}

# ── 휴가 유형 표준 스펙 (data/leave_type_data.xml 과 일치 유지) ──
LEAVE_TYPE_SPECS = {
    "escon_eapproval.leave_type_annual": {
        "name": "연차", "active": True, "requires_allocation": "yes",
        "employee_requests": "no", "allocation_validation_type": "hr",
        "leave_validation_type": "manager", "request_unit": "half_day",
        "support_document": False,
    },
    "escon_eapproval.leave_type_family_event": {
        "name": "경조사", "active": True, "requires_allocation": "no",
        "leave_validation_type": "manager", "request_unit": "day",
        "support_document": False,
    },
    "escon_eapproval.leave_type_official": {
        "name": "공가", "active": True, "requires_allocation": "no",
        "leave_validation_type": "hr", "request_unit": "day",
        "support_document": True,
    },
    "escon_eapproval.leave_type_comp_off": {
        "name": "대체휴무", "active": True, "requires_allocation": "yes",
        "employee_requests": "no", "allocation_validation_type": "hr",
        "leave_validation_type": "manager", "request_unit": "half_day",
        "support_document": False,
    },
}

PROTECTED_LEAVE_TYPE_FIELDS = {
    "name", "active", "requires_allocation", "employee_requests",
    "allocation_validation_type", "leave_validation_type", "request_unit",
    "support_document",
}


class EsconEapprovalSetup(models.AbstractModel):
    _name = "escon.eapproval.setup"
    _description = "Odoo 전자결재 기본 셋팅 자동화"

    @api.model
    def _enforce_specs(self, specs):
        """스펙과 다른 값만 강제 정합. 되돌린 (레코드, 필드들) 목록 반환."""
        fixed = []
        for xmlid, spec in specs.items():
            record = self.env.ref(xmlid, raise_if_not_found=False)
            if not record:
                continue
            record = record.with_context(**{SETUP_CTX: True, "active_test": False})
            diff = {
                field: value for field, value in spec.items()
                if record[field] != value
            }
            if diff:
                record.write(diff)
                fixed.append((record.display_name, sorted(diff)))
        return fixed

    @api.model
    def apply_odoo_defaults(self):
        archived = []
        for xmlid in DEFAULT_CATEGORY_XMLIDS:
            category = self.env.ref(xmlid, raise_if_not_found=False)
            if category and category.active:
                category.active = False
                archived.append(category.name)

        # 별도 "결재" 앱 메뉴 숨김 — 에스콘 전자결재 앱 안으로 통합했으므로 중복 노출 방지
        menu_hidden = False
        root_menu = self.env.ref("approvals.approvals_menu_root", raise_if_not_found=False)
        if root_menu and root_menu.active:
            root_menu.active = False
            menu_hidden = True

        # 표준 스펙 강제 정합 (UI 에서 바뀐 구조 설정을 되돌린다)
        fixed = self._enforce_specs(CATEGORY_SPECS)
        fixed += self._enforce_specs(LEAVE_TYPE_SPECS)

        if archived or menu_hidden or fixed:
            _logger.info(
                "Odoo 전자결재 기본 셋팅 적용: 기본 유형 보관 %s / 결재 앱 메뉴 숨김=%s / "
                "스펙 정합 %s", archived or "-", menu_hidden, fixed or "-")
        return {"archived": archived, "menu_hidden": menu_hidden, "fixed": fixed}

    @api.model
    def action_apply_odoo_defaults(self):
        result = self.apply_odoo_defaults()
        parts = []
        if result["archived"]:
            parts.append("기본 유형 %d개 보관" % len(result["archived"]))
        if result["menu_hidden"]:
            parts.append("별도 '결재' 앱 메뉴 숨김")
        if result["fixed"]:
            parts.append("표준 설정으로 되돌림: " + ", ".join(
                "%s(%s)" % (name, "·".join(fields)) for name, fields in result["fixed"]))
        message = " / ".join(parts) or "이미 표준 설정과 일치합니다. 변경 없음."
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Odoo 전자결재 기본 셋팅",
                "message": message,
                "type": "success",
            },
        }


class EsconSettingGuardMixin(models.AbstractModel):
    """escon_eapproval 이 관리하는 설정 레코드의 보호 필드 수정/삭제 차단.

    변경 경로는 코드 하나뿐이다: setup.py 스펙(+data XML) 수정 → 모듈 업그레이드.
    (SETUP_CTX 컨텍스트를 가진 셋업 루틴만 보호 필드를 쓸 수 있다)"""

    _name = "escon.setting.guard.mixin"
    _description = "에스콘 표준 설정 보호"

    _escon_protected_fields = frozenset()

    def _escon_managed_ids(self):
        rows = self.env["ir.model.data"].sudo().search_read(
            [("module", "=", "escon_eapproval"), ("model", "=", self._name),
             ("res_id", "in", self.ids)],
            ["res_id"])
        return {row["res_id"] for row in rows}

    def _escon_guard(self, touched_fields):
        if self.env.context.get(SETUP_CTX) or self.env.context.get(MODULE_UNINSTALL_FLAG):
            return
        managed = self._escon_managed_ids()
        blocked = self.filtered(lambda r: r.id in managed)
        if blocked:
            raise UserError(_(
                "%(records)s: 에스콘 전자결재 표준 설정 항목이라 화면에서 수정/삭제할 수 "
                "없습니다. (보호 항목: %(fields)s)\n"
                "변경이 필요하면 escon_eapproval 모듈의 표준 스펙(models/setup.py)을 "
                "수정한 뒤 모듈을 업그레이드하세요 — 업그레이드 때마다 표준값으로 "
                "자동 정합됩니다.",
                records=", ".join(blocked.mapped("display_name")),
                fields=", ".join(sorted(touched_fields)) or "-",
            ))

    def write(self, vals):
        touched = set(vals) & self._escon_protected_fields
        if touched:
            self._escon_guard(touched)
        return super().write(vals)

    def unlink(self):
        self._escon_guard({_("삭제")})
        return super().unlink()


class ApprovalCategoryGuard(models.Model):
    _name = "approval.category"
    _inherit = ["approval.category", "escon.setting.guard.mixin"]

    _escon_protected_fields = frozenset(PROTECTED_CATEGORY_FIELDS)


class HrLeaveTypeGuard(models.Model):
    _name = "hr.leave.type"
    _inherit = ["hr.leave.type", "escon.setting.guard.mixin"]

    _escon_protected_fields = frozenset(PROTECTED_LEAVE_TYPE_FIELDS)
