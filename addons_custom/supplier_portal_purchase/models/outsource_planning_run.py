import logging
from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class OutsourcePlanningRun(models.Model):
    """외주 부품 조달 계획 실행"""
    _name = "outsource.planning.run"
    _description = "외주 조달 계획 실행"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="계획 번호",
        required=True,
        readonly=True,
        default=lambda self: _("New"),
        copy=False,
    )
    plan_date_from = fields.Date(string="계획 시작일", required=True, tracking=True)
    plan_date_to = fields.Date(string="계획 종료일", required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("calculating", "계산중"),
            ("review", "검토"),
            ("confirmed", "확정"),
            ("done", "완료"),
            ("cancelled", "취소"),
        ],
        string="상태",
        default="draft",
        tracking=True,
    )

    # 수요 데이터 (injection.production.demand 재사용)
    demand_ids = fields.Many2many(
        "injection.production.demand",
        "outsource_planning_demand_rel",
        "planning_id",
        "demand_id",
        string="수요 데이터",
    )

    line_ids = fields.One2many(
        "outsource.planning.line", "planning_run_id", string="조달 계획 라인",
    )
    summary_ids = fields.One2many(
        "outsource.daily.summary", "planning_run_id", string="일별 요약",
    )
    purchase_order_ids = fields.One2many(
        "purchase.order", "outsource_planning_run_id", string="발주서",
    )

    # 통계
    po_count = fields.Integer(compute="_compute_stats", store=True)
    total_outsource_products = fields.Integer(
        string="외주 품목 수", compute="_compute_stats", store=True,
    )
    total_order_qty = fields.Float(
        string="총 발주 수량", compute="_compute_stats", store=True,
    )

    notes = fields.Text(string="비고")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    @api.depends("line_ids", "line_ids.order_qty", "purchase_order_ids")
    def _compute_stats(self):
        for rec in self:
            rec.po_count = len(rec.purchase_order_ids)
            rec.total_outsource_products = len(rec.line_ids.mapped("product_id"))
            rec.total_order_qty = sum(rec.line_ids.mapped("order_qty"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("outsource.planning.run")
                    or _("New")
                )
        return super().create(vals_list)

    def _get_config(self):
        """설정 레코드 조회"""
        config = self.env["injection.planning.config"].search([], limit=1)
        if not config:
            raise models.UserError(_("생산계획 설정이 없습니다."))
        return config

    # ─────────────────────────────────────────────
    # 수요 데이터 로드 (injection.production.demand 연결)
    # ─────────────────────────────────────────────
    def action_load_demands(self):
        """기간 내 수요 데이터 로드"""
        self.ensure_one()
        Demand = self.env["injection.production.demand"]

        demands = Demand.search([
            ("demand_date", ">=", self.plan_date_from),
            ("demand_date", "<=", self.plan_date_to),
            ("state", "in", ("draft", "planned")),
        ])

        self.demand_ids = [(6, 0, demands.ids)]
        self.message_post(body=_("수요 데이터 %d건 로드") % len(demands))
        return True

    # ─────────────────────────────────────────────
    # 외주 부품 수요 계산 (BOM 전개)
    # ─────────────────────────────────────────────
    def action_calculate(self):
        """외주 부품 일별 수요 계산"""
        self.ensure_one()
        self.state = "calculating"

        # 기존 라인 삭제
        self.line_ids.unlink()
        self.summary_ids.unlink()

        config = self._get_config()
        safety_days = config.safety_stock_days or 3

        # 1. BOM 전개하여 외주 부품 일별 수요 추출
        outsource_demands = self._extract_outsource_demands()

        if not outsource_demands:
            self.state = "review"
            self.message_post(body=_("외주 부품 수요가 없습니다."))
            return True

        # 2. 일별 요약 및 계획 라인 생성
        self._create_planning_lines(outsource_demands, safety_days)

        # 3. 일별 요약 생성 (차트용)
        self._create_daily_summary(safety_days)

        self.state = "review"
        self.message_post(body=_("외주 조달 계획 계산 완료: %d개 품목") % self.total_outsource_products)
        return True

    def _extract_outsource_demands(self):
        """완제품 수요에서 외주 부품 일별 수요 추출"""
        # 구조: {(product_id, date): qty}
        demands = defaultdict(float)

        for demand in self.demand_ids:
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

            # BOM 구성품 중 외주 품목 추출
            for bom_line in bom.bom_line_ids:
                component = bom_line.product_id
                if component.is_outsourced:
                    qty_per = bom_line.product_qty / (bom.product_qty or 1)
                    total_qty = demand_qty * qty_per
                    demands[(component.id, demand_date)] += total_qty

        return demands

    def _create_planning_lines(self, outsource_demands, safety_days):
        """외주 부품별 계획 라인 생성"""
        PlanningLine = self.env["outsource.planning.line"]
        Product = self.env["product.product"]

        # 품목별로 그룹핑
        product_demands = defaultdict(dict)  # {product_id: {date: qty}}
        for (product_id, demand_date), qty in outsource_demands.items():
            product_demands[product_id][demand_date] = qty

        for product_id, date_demands in product_demands.items():
            product = Product.browse(product_id)
            partner = product.outsource_partner_id
            leadtime = product.outsource_leadtime or 3

            # 현재 재고
            current_stock = product.qty_available

            for demand_date, demand_qty in sorted(date_demands.items()):
                # 발주일 = 필요일 - 리드타임
                order_date = demand_date - timedelta(days=leadtime)

                # 안전재고 계산 (향후 N일 수요 합계)
                safety_stock = sum(
                    q for d, q in date_demands.items()
                    if demand_date <= d <= demand_date + timedelta(days=safety_days)
                )

                PlanningLine.create({
                    "planning_run_id": self.id,
                    "product_id": product_id,
                    "partner_id": partner.id if partner else False,
                    "demand_date": demand_date,
                    "demand_qty": demand_qty,
                    "order_date": order_date,
                    "leadtime": leadtime,
                    "safety_stock_qty": safety_stock,
                    "current_stock": current_stock,
                })

    def _create_daily_summary(self, safety_days):
        """일별 요약 생성 (차트용)"""
        Summary = self.env["outsource.daily.summary"]

        # 품목별 일별 데이터 집계
        product_daily = defaultdict(lambda: defaultdict(lambda: {
            "demand_qty": 0,
            "order_qty": 0,
        }))

        for line in self.line_ids:
            key = line.product_id.id
            product_daily[key][line.demand_date]["demand_qty"] += line.demand_qty
            product_daily[key][line.order_date]["order_qty"] += line.order_qty

        # 요약 레코드 생성
        for product_id, daily_data in product_daily.items():
            product = self.env["product.product"].browse(product_id)
            stock = product.qty_available  # 시작 재고

            for plan_date in sorted(daily_data.keys()):
                data = daily_data[plan_date]
                demand_qty = data["demand_qty"]
                incoming_qty = data["order_qty"]

                # 안전재고 (향후 N일 수요)
                safety_stock = sum(
                    daily_data[d]["demand_qty"]
                    for d in daily_data
                    if plan_date <= d <= plan_date + timedelta(days=safety_days)
                )

                stock_end = stock + incoming_qty - demand_qty

                Summary.create({
                    "planning_run_id": self.id,
                    "product_id": product_id,
                    "plan_date": plan_date,
                    "demand_qty": demand_qty,
                    "incoming_qty": incoming_qty,
                    "safety_stock_qty": safety_stock,
                    "stock_start": stock,
                    "stock_end": stock_end,
                })

                stock = stock_end

    # ─────────────────────────────────────────────
    # 발주 생성
    # ─────────────────────────────────────────────
    def action_generate_purchase_orders(self):
        """발주서 생성"""
        self.ensure_one()

        if self.state not in ("review", "confirmed"):
            raise models.UserError(_("검토 또는 확정 상태에서만 발주를 생성할 수 있습니다."))

        # 협력사별로 그룹핑
        partner_lines = defaultdict(list)
        for line in self.line_ids.filtered(lambda l: l.partner_id and l.order_qty > 0):
            partner_lines[line.partner_id.id].append(line)

        created_pos = self.env["purchase.order"]

        for partner_id, lines in partner_lines.items():
            po = self._create_purchase_order(partner_id, lines)
            created_pos |= po

        if created_pos:
            self.message_post(
                body=_("발주서 %d건 생성: %s") % (
                    len(created_pos),
                    ", ".join(created_pos.mapped("name"))
                )
            )

        return True

    def _create_purchase_order(self, partner_id, lines):
        """협력사별 발주서 생성"""
        config = self._get_config()

        po = self.env["purchase.order"].create({
            "partner_id": partner_id,
            "outsource_planning_run_id": self.id,
            "auto_generated": True,
            "portal_state": "new",
            "buyer_id": config.default_buyer_id.id if config.default_buyer_id else self.env.user.id,
            "date_order": fields.Datetime.now(),
            "origin": self.name,
        })

        for line in lines:
            product = line.product_id

            # 공급업체 가격 조회
            supplierinfo = self.env["product.supplierinfo"].search([
                ("partner_id", "=", partner_id),
                ("product_tmpl_id", "=", product.product_tmpl_id.id),
            ], limit=1)

            price = supplierinfo.price if supplierinfo else product.standard_price

            self.env["purchase.order.line"].create({
                "order_id": po.id,
                "product_id": product.id,
                "product_qty": line.order_qty,
                "price_unit": price,
                "date_planned": line.demand_date,
            })

        # 협력사 알림
        po._create_portal_notification("new_po", partner=po.partner_id)

        return po

    # ─────────────────────────────────────────────
    # 상태 변경
    # ─────────────────────────────────────────────
    def action_confirm(self):
        """계획 확정"""
        self.ensure_one()
        self.state = "confirmed"
        return True

    def action_done(self):
        """완료 처리"""
        self.ensure_one()
        self.state = "done"
        return True

    def action_cancel(self):
        """취소"""
        self.ensure_one()
        self.state = "cancelled"
        return True

    def action_reset_draft(self):
        """초안으로 되돌리기"""
        self.ensure_one()
        self.state = "draft"
        return True

    # ─────────────────────────────────────────────
    # 보기 액션
    # ─────────────────────────────────────────────
    def action_view_purchase_orders(self):
        """발주서 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("외주 발주서"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("outsource_planning_run_id", "=", self.id)],
            "context": {"default_outsource_planning_run_id": self.id},
        }

    def action_view_daily_chart(self):
        """일별 분석 차트 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("외주 부품 일별 분석"),
            "res_model": "outsource.daily.summary",
            "view_mode": "graph,pivot,list",
            "domain": [("planning_run_id", "=", self.id)],
            "context": {"default_planning_run_id": self.id},
        }
