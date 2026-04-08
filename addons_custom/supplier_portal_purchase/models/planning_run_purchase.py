from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _


class InjectionPlanningRun(models.Model):
    """생산계획에 외주 발주 자동 생성 기능 추가"""
    _inherit = "injection.planning.run"

    purchase_order_ids = fields.One2many(
        "purchase.order",
        "planning_run_id",
        string="자동 생성 발주",
    )
    purchase_order_count = fields.Integer(
        string="발주 건수",
        compute="_compute_purchase_order_count",
    )
    outsource_line_count = fields.Integer(
        string="외주 품목 수",
        compute="_compute_outsource_stats",
    )

    @api.depends("purchase_order_ids")
    def _compute_purchase_order_count(self):
        for run in self:
            run.purchase_order_count = len(run.purchase_order_ids)

    @api.depends("line_ids", "line_ids.product_id")
    def _compute_outsource_stats(self):
        for run in self:
            outsource_lines = run.line_ids.filtered(
                lambda l: l.product_id.is_outsourced
            )
            run.outsource_line_count = len(outsource_lines)

    def action_confirm_generate_mo(self):
        """MO 생성 후 외주 발주 자동 생성"""
        res = super().action_confirm_generate_mo()

        config = self._get_config()
        if config.auto_generate_po:
            self._generate_outsource_purchase_orders()

        return res

    def _generate_outsource_purchase_orders(self):
        """외주 품목에 대한 발주서 자동 생성"""
        self.ensure_one()

        # 1. BOM에서 외주 품목 수요 추출
        outsource_demands = self._extract_outsource_demands()

        if not outsource_demands:
            self.message_post(body=_("외주 품목이 없어 발주서가 생성되지 않았습니다."))
            return

        # 2. 협력사별로 그룹핑
        partner_demands = defaultdict(list)
        for demand in outsource_demands:
            partner_id = demand["partner_id"]
            if partner_id:
                partner_demands[partner_id].append(demand)

        # 3. PO 생성
        created_pos = self.env["purchase.order"]
        for partner_id, demands in partner_demands.items():
            po = self._create_purchase_order(partner_id, demands)
            created_pos |= po

        if created_pos:
            self.message_post(
                body=_(
                    "외주 발주서 %d건이 자동 생성되었습니다: %s"
                ) % (len(created_pos), ", ".join(created_pos.mapped("name")))
            )

    def _extract_outsource_demands(self):
        """완제품 수요의 BOM에서 외주 품목 수요 추출"""
        demands = []
        config = self._get_config()
        buffer_days = config.outsource_buffer_days or 1

        # 완제품 수요 데이터에서 외주 부품 추출
        for demand in self.demand_ids.filtered(lambda d: d.state in ("draft", "planned")):
            product = demand.product_id  # 완제품
            demand_date = demand.demand_date
            demand_qty = demand.quantity

            # 완제품 BOM 찾기
            bom = self.env["mrp.bom"].search([
                "|",
                ("product_id", "=", product.id),
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
            ], limit=1)

            if not bom:
                continue

            # BOM 구성품 중 외주 품목 확인
            for bom_line in bom.bom_line_ids:
                component = bom_line.product_id
                if component.is_outsourced and component.outsource_partner_id:
                    qty_per = bom_line.product_qty / (bom.product_qty or 1)
                    total_qty = demand_qty * qty_per
                    required_date = demand_date - timedelta(
                        days=(component.outsource_leadtime or 3) + buffer_days
                    )
                    demands.append({
                        "product_id": component.id,
                        "partner_id": component.outsource_partner_id.id,
                        "qty": total_qty,
                        "required_date": required_date,
                        "demand_id": demand.id,
                    })

        # 같은 협력사, 같은 제품, 같은 납기일 수요 합산
        merged = {}
        for d in demands:
            key = (d["partner_id"], d["product_id"], d["required_date"])
            if key in merged:
                merged[key]["qty"] += d["qty"]
            else:
                merged[key] = d.copy()

        return list(merged.values())

    def _create_purchase_order(self, partner_id, demands):
        """협력사별 발주서 생성"""
        partner = self.env["res.partner"].browse(partner_id)
        config = self._get_config()

        # PO 생성
        po_vals = {
            "partner_id": partner_id,
            "planning_run_id": self.id,
            "auto_generated": True,
            "portal_state": "new",
            "buyer_id": config.default_buyer_id.id if config.default_buyer_id else self.env.user.id,
            "date_order": fields.Datetime.now(),
            "origin": self.name,
        }

        po = self.env["purchase.order"].create(po_vals)

        # PO Lines 생성
        for demand in demands:
            product = self.env["product.product"].browse(demand["product_id"])

            # 공급업체 가격 조회
            supplierinfo = self.env["product.supplierinfo"].search([
                ("partner_id", "=", partner_id),
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
            ], limit=1)

            price = supplierinfo.price if supplierinfo else product.standard_price

            self.env["purchase.order.line"].create({
                "order_id": po.id,
                "product_id": demand["product_id"],
                "product_qty": demand["qty"],
                "price_unit": price,
                "date_planned": demand["required_date"],
                "demand_id": demand.get("demand_id"),
            })

        # 협력사에게 알림
        po._create_portal_notification("new_po", partner=partner)

        return po

    def action_view_purchase_orders(self):
        """자동 생성된 발주서 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("자동 생성 발주"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("planning_run_id", "=", self.id)],
            "context": {"default_planning_run_id": self.id},
        }

    def action_generate_purchase_orders(self):
        """수동으로 외주 발주 생성"""
        self.ensure_one()
        self._generate_outsource_purchase_orders()
        return True
