"""Odoo 기본 전자결재(Approvals) 셋팅 자동화.

Odoo 가 기본 제공하는 영문 요청 유형(Business Trip, Payment Application …)을
회사 유형(일반 결재/경비청구서/출장/자동차 대여/출입신청/RFQ)으로 교체하는
설정 작업을 코드로 재현 가능하게 만든다.

실행 시점
- 모듈 설치/업그레이드 때마다: data/approval_setup.xml 의 <function> 호출 (멱등)
- 수동: 에스콘 전자결재 > 설정 > "Odoo 전자결재 기본 셋팅 재적용"
"""

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

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


class EsconEapprovalSetup(models.AbstractModel):
    _name = "escon.eapproval.setup"
    _description = "Odoo 전자결재 기본 셋팅 자동화"

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

        if archived or menu_hidden:
            _logger.info("Odoo 전자결재 기본 셋팅 적용: 기본 유형 보관 %s, 결재 앱 메뉴 숨김=%s",
                         archived or "-", menu_hidden)
        return {"archived": archived, "menu_hidden": menu_hidden}

    @api.model
    def action_apply_odoo_defaults(self):
        result = self.apply_odoo_defaults()
        if result["archived"] or result["menu_hidden"]:
            message = "기본 유형 %d개 보관 처리" % len(result["archived"])
            if result["menu_hidden"]:
                message += ", 별도 '결재' 앱 메뉴 숨김"
        else:
            message = "이미 적용되어 있습니다. 변경 없음."
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Odoo 전자결재 기본 셋팅",
                "message": message,
                "type": "success",
            },
        }
