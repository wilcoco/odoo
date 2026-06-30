from odoo import api, fields, models, _


class PurchaseOrderOverdue(models.Model):
    """납품 실패(납기 경과 미입고) 감지 + 생산영향 경고/에스컬레이션.

    기존 '미응답 리마인더'는 발주에 응답이 없을 때, '입고예정 리마인더'는 예정 입고 안내용.
    여기서는 '납기가 지났는데 아직 입고 안 된' 실제 납품 실패를 감지해, 어느 생산오더가
    막히는지 식별하고 공급사·담당자에게 경고한다.
    """

    _inherit = "purchase.order"

    has_overdue_receipt = fields.Boolean(
        string="납품 지연", compute="_compute_has_overdue_receipt",
        help="이 발주의 입고가 납기를 지나도록 완료되지 않음")

    def _compute_has_overdue_receipt(self):
        now = fields.Datetime.now()
        for po in self:
            po.has_overdue_receipt = any(
                p.picking_type_id.code == "incoming"
                and p.state not in ("done", "cancel")
                and p.scheduled_date and p.scheduled_date < now
                for p in po.picking_ids)

    def _impacted_productions(self):
        """이 발주 미입고로 자재가 부족해지는 생산오더."""
        self.ensure_one()
        products = self.order_line.mapped("product_id")
        if not products:
            return self.env["mrp.production"]
        mos = self.env["mrp.production"].search([
            ("state", "in", ("confirmed", "progress")),
            ("move_raw_ids.product_id", "in", products.ids),
        ])
        return mos.filtered(lambda m: any(
            mv.product_id in products
            and (mv.product_id.free_qty < mv.product_uom_qty)
            for mv in m.move_raw_ids))

    def action_alert_overdue(self):
        """납품 지연 경고: 공급사 알림 + 담당자 할일 + 생산영향 기록."""
        Notif = self.env["supplier.portal.notification"]
        for po in self:
            impacted = po._impacted_productions()
            Notif.create({
                "partner_id": po.partner_id.id,
                "purchase_order_id": po.id,
                "notification_type": "delivery_overdue",
                "message": _("발주 %s 납기 경과 미입고입니다. 즉시 납품 바랍니다.") % po.name,
            })
            note = _("납기 경과 미입고. 영향 생산오더 %(n)d건: %(mos)s") % {
                "n": len(impacted),
                "mos": ", ".join(impacted.mapped("name")) or _("없음")}
            po.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("⚠️ 납품 지연: %s") % po.name,
                note=note,
                user_id=po.user_id.id or self.env.user.id)
            if impacted:
                # 영향 생산오더에 생산영향 알림
                Notif.create({
                    "partner_id": po.partner_id.id,
                    "purchase_order_id": po.id,
                    "notification_type": "production_impact",
                    "message": _("발주 %(po)s 지연으로 생산 영향: %(mos)s") % {
                        "po": po.name, "mos": ", ".join(impacted.mapped("name"))},
                })
                po.message_post(body=_("⚠️ 납품지연 영향 생산오더: %s") % ", ".join(impacted.mapped("name")))
            else:
                po.message_post(body=_("납품 지연 — 현재 직접 막힌 생산오더 없음."))
        return True

    @api.model
    def _cron_check_overdue_deliveries(self):
        """스케줄러: 납기 경과 미입고 발주 감지 → 경고(하루 1회 중복방지)."""
        today = fields.Datetime.to_datetime(fields.Date.today())
        confirmed = self.search([("state", "=", "purchase")])
        overdue = confirmed.filtered(lambda po: po.has_overdue_receipt)
        for po in overdue:
            already = self.env["supplier.portal.notification"].search_count([
                ("purchase_order_id", "=", po.id),
                ("notification_type", "=", "delivery_overdue"),
                ("create_date", ">=", today),
            ])
            if not already:
                po.action_alert_overdue()
        return True
