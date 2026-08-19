from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    """발주서에 포탈 관련 필드 추가"""
    _inherit = "purchase.order"

    outsource_planning_run_id = fields.Many2one(
        "outsource.planning.run",
        string="연결된 외주계획",
        readonly=True,
    )
    auto_generated = fields.Boolean(
        string="자동 생성",
        default=False,
        readonly=True,
        help="생산계획에서 자동으로 생성된 발주서",
    )
    is_portal_po = fields.Boolean(
        string="포탈 대상 발주",
        related="partner_id.is_supplier_portal",
        store=True,
        help="협력사 포탈을 사용하는 업체 앞 발주 — 자동/수동 구분 없이 포탈 목록·통계·리마인더의 단일 기준",
    )
    portal_state = fields.Selection(
        [
            ("new", "응답 대기"),
            ("responded", "응답 완료"),
            ("approved", "승인"),
            ("rejected", "반려"),
            ("done", "납품 완료"),
        ],
        string="포탈 상태",
        default="new",
        tracking=True,
    )
    buyer_id = fields.Many2one(
        "res.users",
        string="담당 구매자",
        default=lambda self: self.env.user,
    )
    response_ids = fields.One2many(
        "purchase.order.response",
        "purchase_order_id",
        string="협력사 응답",
    )
    latest_response_id = fields.Many2one(
        "purchase.order.response",
        string="최근 응답",
        compute="_compute_latest_response",
        store=True,
    )
    production_impact = fields.Selection(
        [
            ("ok", "정상"),
            ("warning", "주의"),
            ("critical", "위험"),
        ],
        string="생산 영향도",
        compute="_compute_production_impact",
        store=True,
    )
    portal_url = fields.Char(
        string="포탈 URL",
        compute="_compute_portal_url",
    )

    @api.depends("response_ids", "response_ids.create_date")
    def _compute_latest_response(self):
        for po in self:
            responses = po.response_ids.sorted("create_date", reverse=True)
            po.latest_response_id = responses[0] if responses else False

    @api.depends("latest_response_id", "latest_response_id.line_response_ids")
    def _compute_production_impact(self):
        for po in self:
            if not po.latest_response_id:
                po.production_impact = "ok"
                continue

            # 응답 라인에서 최대 영향도 계산
            max_impact = "ok"
            for line_resp in po.latest_response_id.line_response_ids:
                if line_resp.line_status == "reject":
                    max_impact = "critical"
                    break
                elif line_resp.line_status in ("date_diff", "both_diff"):
                    # 납기 차이 일수 확인 (requested_date는 Datetime, confirmed_date는 Date)
                    if line_resp.confirmed_date and line_resp.requested_date:
                        req_date = line_resp.requested_date.date()
                        diff = (line_resp.confirmed_date - req_date).days
                        if diff > 1:
                            max_impact = "critical"
                        elif diff > 0 and max_impact != "critical":
                            max_impact = "warning"
                elif line_resp.line_status == "qty_diff" and max_impact == "ok":
                    max_impact = "warning"

            po.production_impact = max_impact

    def _compute_portal_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        for po in self:
            if po.partner_id.supplier_portal_token:
                po.portal_url = (
                    f"{base_url}/supplier/po/{po.id}"
                    f"?token={po.partner_id.supplier_portal_token}"
                )
            else:
                po.portal_url = False

    @api.model
    def _portal_visible_domain(self, partner_id=None):
        """협력사 포탈에 노출되는 발주의 단일 기준 — 대시보드 집계·목록·납품현황·리마인더가 모두 이 도메인을 쓴다.

        - 자동발주(auto_generated): 초안 상태부터 노출 (협력사 응답 → 승인 시 확정되는 흐름)
        - 수동발주: 구매담당자가 확정(purchase/done)한 뒤에만 노출 (작성 중 RFQ 가 협력사에 보이면 안 됨)
        - 취소 발주 제외
        """
        domain = [
            ("is_portal_po", "=", True),
            ("state", "!=", "cancel"),
            "|", ("auto_generated", "=", True), ("state", "in", ("purchase", "done")),
        ]
        if partner_id:
            domain.insert(0, ("partner_id", "=", partner_id))
        return domain

    def button_confirm(self):
        """수동 발주도 포탈 협력사에게 '새 발주' 알림 — 자동발주(_create_purchase_order)는 이미 보냈으므로 제외."""
        res = super().button_confirm()
        Notification = self.env["supplier.portal.notification"].sudo()
        for po in self.filtered(lambda p: p.is_portal_po and not p.auto_generated):
            already = Notification.search_count([
                ("purchase_order_id", "=", po.id),
                ("notification_type", "=", "new_po"),
            ])
            if not already:
                po._create_portal_notification("new_po", partner=po.partner_id)
        return res

    def _portal_mark_done_from_receipt(self):
        """입고 전표 확정 훅에서 호출 — 모든 입고가 완료된 포탈 발주를 '납품완료'로 자동 전이."""
        for po in self.filtered(lambda p: p.is_portal_po and p.portal_state != "done"):
            pickings = po.picking_ids
            # purchase_stock 의 receipt_status='full' 과 동일 판정을 인라인으로 (recompute 타이밍 비의존)
            if pickings and all(p.state in ("done", "cancel") for p in pickings) \
                    and any(p.state == "done" for p in pickings):
                po.action_mark_done()

    def action_approve_response(self):
        """협력사 응답 승인"""
        self.ensure_one()
        if self.portal_state != "responded":
            raise UserError(_("응답 완료 상태의 발주만 승인할 수 있습니다."))

        # PO Line에 확정 수량/납기 반영
        if self.latest_response_id:
            for line_resp in self.latest_response_id.line_response_ids:
                if line_resp.is_approved:
                    line_resp.order_line_id.write({
                        "product_qty": line_resp.confirmed_qty,
                        "date_planned": line_resp.confirmed_date,
                    })

        # 발주 확정 (입고 대기 생성)
        if self.state in ("draft", "sent"):
            self.button_confirm()

        self.portal_state = "approved"

        # 협력사에게 승인 알림
        self._create_portal_notification("approved", partner=self.partner_id)

        self.message_post(body=_("협력사 응답이 승인되었습니다. 입고 대기가 생성되었습니다."))
        return True

    def action_reject_response(self):
        """협력사 응답 반려 위자드 열기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "응답 반려",
            "res_model": "purchase.order.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_purchase_order_id": self.id},
        }

    def action_mark_done(self):
        """납품 완료 처리"""
        self.ensure_one()
        self.portal_state = "done"
        self._create_portal_notification("delivery_done", partner=self.partner_id)
        return True

    def _create_portal_notification(self, notification_type, partner=None, user=None):
        """포탈 알림 생성"""
        message_map = {
            "new_po": _("새로운 발주가 도착했습니다."),
            "confirm_request": _("응답을 제출해 주세요."),
            "response_received": _("협력사가 응답을 제출했습니다."),
            "approved": _("발주가 승인되었습니다."),
            "rejected": _("발주가 반려되었습니다. 재응답이 필요합니다."),
            "delivery_done": _("입고가 완료되었습니다."),
        }

        self.env["supplier.portal.notification"].create({
            "partner_id": partner.id if partner else False,
            "user_id": user.id if user else False,
            "notification_type": notification_type,
            "purchase_order_id": self.id,
            "message": message_map.get(notification_type, ""),
        })


    @api.model
    def _cron_send_reminder_notifications(self):
        """미응답 발주에 대해 리마인더 알림 생성 (Cron)"""
        config = self.env["outsource.planning.config"].search([], limit=1)
        reminder_days = config.po_reminder_days if config else 2

        # 납기 D-N일 이내 미응답 발주 조회
        from datetime import timedelta
        target_date = fields.Date.today() + timedelta(days=reminder_days)

        # date_planned는 PO Line에 있으므로 서브쿼리로 최소 납기일 확인
        pending_pos = self.search(self._portal_visible_domain() + [
            ("portal_state", "=", "new"),
        ])

        # 납기일 기준 필터링
        urgent_pos = pending_pos.filtered(
            lambda po: po.order_line and min(
                (l.date_planned.date() if l.date_planned else fields.Date.today())
                for l in po.order_line
            ) <= target_date
        )

        for po in urgent_pos:
            # 이미 오늘 리마인더 보냈는지 확인
            existing = self.env["supplier.portal.notification"].search([
                ("purchase_order_id", "=", po.id),
                ("notification_type", "=", "confirm_request"),
                ("create_date", ">=", fields.Datetime.to_datetime(fields.Date.today())),
            ], limit=1)

            if not existing:
                po._create_portal_notification("confirm_request", partner=po.partner_id)


class PurchaseOrderLine(models.Model):
    """발주 라인에 수요 데이터 연결"""
    _inherit = "purchase.order.line"

    demand_id = fields.Many2one(
        "production.demand",
        string="수요 데이터",
        readonly=True,
    )
