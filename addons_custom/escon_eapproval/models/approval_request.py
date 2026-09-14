from odoo import fields, models


class IatfApprovalRequest(models.Model):
    """iatf_approval 결재 엔진 필드/상태 라벨 한글화 (전사 전자결재 승격에 따라).

    selection 키는 그대로 두고 라벨만 바꾼다 — 저장값·기존 로직에 영향 없음.
    이 라벨은 결재 mixin 을 쓰는 모든 문서(품의서·IATF 문서 등)에 공통 적용된다."""

    _inherit = "iatf.approval.request"

    state = fields.Selection(selection=[
        ("draft", "임시저장"),
        ("in_progress", "결재 중"),
        ("approved", "승인"),
        ("rejected", "반려"),
    ])
    requester_id = fields.Many2one(string="상신자")
    current_approver_id = fields.Many2one(string="현재 결재자")
    approved_date = fields.Datetime(string="승인 일시")
    rejected_date = fields.Datetime(string="반려 일시")
    line_ids = fields.One2many(string="결재선")


class IatfApprovalLine(models.Model):
    _inherit = "iatf.approval.line"

    state = fields.Selection(selection=[
        ("new", "대기"),
        ("pending", "결재 차례"),
        ("approved", "승인"),
        ("rejected", "반려"),
    ])
    user_id = fields.Many2one(string="결재자")
    action_date = fields.Datetime(string="처리 일시")
    note = fields.Char(string="의견")


class IatfApprovalMixin(models.AbstractModel):
    _inherit = "iatf.approval.mixin"

    approval_state = fields.Selection(string="결재 상태")
    approval_line_ids = fields.One2many(string="결재선")
    approval_current_approver_id = fields.Many2one(string="현재 결재자")
