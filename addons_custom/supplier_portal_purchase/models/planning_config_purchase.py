from odoo import fields, models


class InjectionPlanningConfig(models.Model):
    """생산계획 설정에 외주 관련 설정 추가"""
    _inherit = "injection.planning.config"

    # 외주 발주 설정
    auto_generate_po = fields.Boolean(
        string="자동 발주 생성",
        default=False,
        help="생산계획 확정 시 외주 품목에 대해 자동으로 발주서 생성",
    )
    outsource_buffer_days = fields.Integer(
        string="외주 납기 버퍼 (일)",
        default=1,
        help="필요 납기일 = 생산일 - 리드타임 - 버퍼일",
    )
    default_buyer_id = fields.Many2one(
        "res.users",
        string="기본 구매 담당자",
        help="자동 생성 발주의 기본 담당자",
    )

    # 포탈 설정
    portal_base_url = fields.Char(
        string="포탈 기본 URL",
        help="협력사 포탈 접근 URL (미입력 시 시스템 기본값 사용)",
    )
    po_reminder_days = fields.Integer(
        string="리마인더 발송일 (D-N)",
        default=2,
        help="납기 N일 전 미응답 발주에 대해 리마인더 알림",
    )

    # 생산 영향 알림 설정
    notify_production_impact = fields.Boolean(
        string="생산 영향 알림",
        default=True,
        help="협력사 응답이 생산에 영향을 미칠 경우 생산관리자에게 알림",
    )
    production_manager_id = fields.Many2one(
        "res.users",
        string="생산 관리자",
        help="생산 영향 알림을 받을 담당자",
    )
