import secrets

from odoo import api, fields, models


class ResPartner(models.Model):
    """협력사에 포탈 접근 정보 추가"""
    _inherit = "res.partner"

    is_supplier_portal = fields.Boolean(
        string="협력사 포탈 사용",
        default=False,
        help="협력사 포탈을 통해 발주 확인/응답 가능",
    )
    supplier_portal_token = fields.Char(
        string="포탈 접근 토큰",
        copy=False,
        help="협력사 포탈 접근용 보안 토큰",
    )
    portal_notify_email = fields.Char(
        string="발주 알림 이메일",
        help="발주 알림을 받을 이메일 주소 (미입력 시 기본 이메일 사용)",
    )
    portal_language = fields.Selection(
        [
            ("ko_KR", "한국어"),
            ("en_US", "English"),
        ],
        string="포탈 언어",
        default="ko_KR",
    )
    # 통계 필드
    supplier_po_count = fields.Integer(
        string="발주 건수",
        compute="_compute_supplier_stats",
    )
    supplier_pending_count = fields.Integer(
        string="응답 대기 건수",
        compute="_compute_supplier_stats",
    )

    @api.depends("is_supplier_portal")
    def _compute_supplier_stats(self):
        PO = self.env["purchase.order"]
        for partner in self:
            if partner.is_supplier_portal:
                partner.supplier_po_count = PO.search_count([
                    ("partner_id", "=", partner.id),
                    ("auto_generated", "=", True),
                ])
                partner.supplier_pending_count = PO.search_count([
                    ("partner_id", "=", partner.id),
                    ("portal_state", "=", "new"),
                ])
            else:
                partner.supplier_po_count = 0
                partner.supplier_pending_count = 0

    def action_generate_portal_token(self):
        """포탈 접근 토큰 생성"""
        for partner in self:
            partner.supplier_portal_token = secrets.token_urlsafe(32)
        return True

    def action_view_supplier_pos(self):
        """협력사의 발주 목록 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": f"{self.name} 발주 목록",
            "res_model": "purchase.order",
            "view_mode": "tree,form",
            "domain": [
                ("partner_id", "=", self.id),
                ("auto_generated", "=", True),
            ],
            "context": {"default_partner_id": self.id},
        }
