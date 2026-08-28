import logging
from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class SupplyChainRoute(models.Model):
    """다단계 공급 경로 정의"""
    _name = "supply.chain.route"
    _description = "공급 경로"
    _order = "name"

    name = fields.Char(string="경로명", required=True)
    product_id = fields.Many2one(
        "product.product",
        string="외주 부품",
        required=True,
        domain="[('is_outsourced', '=', True)]",
    )
    active = fields.Boolean(default=True)

    tier_ids = fields.One2many(
        "supply.chain.tier",
        "route_id",
        string="공급 단계",
    )
    tier_count = fields.Integer(
        string="단계 수",
        compute="_compute_stats",
        store=True,
    )
    total_leadtime = fields.Integer(
        string="총 리드타임 (일)",
        compute="_compute_stats",
        store=True,
        help="모든 단계의 리드타임 합계",
    )
    final_supplier_id = fields.Many2one(
        "res.partner",
        string="최종 납품업체",
        compute="_compute_stats",
        store=True,
        help="우리회사에 직접 납품하는 업체",
    )

    notes = fields.Text(string="비고")
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
    )

    @api.depends("tier_ids", "tier_ids.leadtime", "tier_ids.sequence")
    def _compute_stats(self):
        for route in self:
            tiers = route.tier_ids.sorted("sequence")
            route.tier_count = len(tiers)
            route.total_leadtime = sum(tiers.mapped("leadtime"))
            # 최종 납품업체 = 가장 마지막 단계 (sequence가 가장 큰)
            route.final_supplier_id = tiers[-1].supplier_id if tiers else False

    def action_view_tiers(self):
        """공급 단계 보기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("공급 단계: %s") % self.name,
            "res_model": "supply.chain.tier",
            "view_mode": "list,form",
            "domain": [("route_id", "=", self.id)],
            "context": {"default_route_id": self.id},
        }


class SupplyChainTier(models.Model):
    """공급 경로의 각 단계"""
    _name = "supply.chain.tier"
    _description = "공급 단계"
    _order = "route_id, sequence"

    route_id = fields.Many2one(
        "supply.chain.route",
        string="공급 경로",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(
        string="순서",
        default=10,
        help="1=1차 공급업체, 숫자가 클수록 최종 납품에 가까움",
    )
    name = fields.Char(
        string="단계명",
        compute="_compute_name",
        store=True,
    )

    supplier_id = fields.Many2one(
        "res.partner",
        string="협력사",
        required=True,
        domain="[('is_supplier_portal', '=', True)]",
    )
    leadtime = fields.Integer(
        string="리드타임 (일)",
        default=3,
        required=True,
        help="이 단계에서 다음 단계(또는 우리회사)까지 소요 기간",
    )

    # 단계 유형 및 생산/조립 정보
    tier_type = fields.Selection(
        [
            ("produce", "생산"),
            ("assemble", "조립"),
            ("deliver", "납품만"),
        ],
        string="단계 유형",
        default="produce",
        help="생산: 원자재→부품, 조립: 부품+자체부품→조립품, 납품만: 단순 전달",
    )
    output_product_id = fields.Many2one(
        "product.product",
        string="산출 부품",
        help="이 단계에서 생산/조립되는 부품",
    )
    input_product_ids = fields.Many2many(
        "product.product",
        "supply_tier_input_product_rel",
        "tier_id",
        "product_id",
        string="입고 부품",
        help="이전 단계에서 받는 부품들",
    )
    additional_component_ids = fields.Many2many(
        "product.product",
        "supply_tier_additional_product_rel",
        "tier_id",
        "product_id",
        string="추가 자재",
        help="이 단계에서 자체 조달하는 추가 부품들",
    )
    delivers_to = fields.Selection(
        [
            ("next_tier", "다음 단계"),
            ("company", "우리회사"),
        ],
        string="납품처",
        compute="_compute_delivers_to",
        store=True,
    )

    # 다음 단계 정보
    next_tier_id = fields.Many2one(
        "supply.chain.tier",
        string="다음 단계",
        compute="_compute_next_tier",
    )
    next_supplier_id = fields.Many2one(
        "res.partner",
        string="다음 협력사",
        compute="_compute_next_tier",
    )

    # 누적 리드타임
    cumulative_leadtime = fields.Integer(
        string="누적 리드타임",
        compute="_compute_cumulative_leadtime",
        store=True,
        help="이 단계부터 최종 납품까지의 리드타임",
    )

    product_id = fields.Many2one(
        related="route_id.product_id",
        store=True,
    )

    @api.depends("sequence", "route_id.tier_ids.sequence")
    def _compute_name(self):
        # 경로 내 순번(1,2,3…)으로 'N차 공급' 표시.
        # sequence 는 10/20 처럼 띄엄띄엄일 수 있어 raw 값을 그대로 쓰면 '10차'가 됨 → 순위로 환산.
        for tier in self:
            siblings = tier.route_id.tier_ids.sorted("sequence")
            rank = (list(siblings).index(tier) + 1) if tier in siblings else 1
            tier.name = f"{rank}차 공급"

    @api.depends("route_id.tier_ids", "sequence")
    def _compute_delivers_to(self):
        for tier in self:
            tiers = tier.route_id.tier_ids.sorted("sequence")
            if tiers and tier == tiers[-1]:
                tier.delivers_to = "company"
            else:
                tier.delivers_to = "next_tier"

    @api.depends("route_id.tier_ids", "sequence")
    def _compute_next_tier(self):
        for tier in self:
            tiers = tier.route_id.tier_ids.sorted("sequence")
            tier_list = list(tiers)
            try:
                idx = tier_list.index(tier)
                if idx < len(tier_list) - 1:
                    tier.next_tier_id = tier_list[idx + 1]
                    tier.next_supplier_id = tier_list[idx + 1].supplier_id
                else:
                    tier.next_tier_id = False
                    tier.next_supplier_id = False
            except (ValueError, IndexError):
                tier.next_tier_id = False
                tier.next_supplier_id = False

    @api.depends("route_id.tier_ids", "route_id.tier_ids.leadtime", "sequence")
    def _compute_cumulative_leadtime(self):
        """이 단계부터 최종 납품까지의 누적 리드타임"""
        for tier in self:
            tiers = tier.route_id.tier_ids.sorted("sequence")
            tier_list = list(tiers)
            try:
                idx = tier_list.index(tier)
                # 이 단계부터 끝까지의 리드타임 합
                tier.cumulative_leadtime = sum(
                    t.leadtime for t in tier_list[idx:]
                )
            except ValueError:
                tier.cumulative_leadtime = tier.leadtime


class SupplyChainOrder(models.Model):
    """다단계 발주 추적"""
    _name = "supply.chain.order"
    _description = "공급망 발주 추적"
    _order = "create_date desc"
    _inherit = ["mail.thread"]

    name = fields.Char(
        string="추적번호",
        required=True,
        readonly=True,
        default=lambda self: _("New"),
        copy=False,
    )
    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="발주서",
        required=True,
        ondelete="cascade",
    )
    route_id = fields.Many2one(
        "supply.chain.route",
        string="공급 경로",
        required=True,
    )
    product_id = fields.Many2one(
        related="route_id.product_id",
        store=True,
    )

    # 단계별 상태 추적
    tier_status_ids = fields.One2many(
        "supply.chain.order.status",
        "chain_order_id",
        string="단계별 상태",
    )

    # 전체 상태
    state = fields.Selection(
        [
            ("pending", "대기"),
            ("in_progress", "진행중"),
            ("completed", "완료"),
            ("issue", "이슈 발생"),
        ],
        string="상태",
        compute="_compute_state",
        store=True,
        tracking=True,
    )
    progress_percent = fields.Float(
        string="진행률 (%)",
        compute="_compute_state",
        store=True,
    )

    required_date = fields.Date(string="납기일", required=True)
    notes = fields.Text(string="비고")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("supply.chain.order")
                    or _("New")
                )
        return super().create(vals_list)

    @api.depends("tier_status_ids", "tier_status_ids.state")
    def _compute_state(self):
        for order in self:
            statuses = order.tier_status_ids
            if not statuses:
                order.state = "pending"
                order.progress_percent = 0
                continue

            total = len(statuses)
            completed = len(statuses.filtered(lambda s: s.state == "completed"))
            has_issue = any(s.state == "issue" for s in statuses)

            order.progress_percent = (completed / total * 100) if total else 0

            if has_issue:
                order.state = "issue"
            elif completed == total:
                order.state = "completed"
            elif completed > 0:
                order.state = "in_progress"
            else:
                order.state = "pending"

    def action_init_tier_status(self):
        """공급 경로의 각 단계별 상태 레코드 생성 (UI 버튼용)"""
        self.ensure_one()
        self._init_tier_status_with_dates(self.required_date)
        return True

    def _init_tier_status_with_dates(self, required_date):
        """공급 경로의 각 단계별 상태 레코드 생성 (날짜 계산 포함)"""
        from datetime import timedelta

        Status = self.env["supply.chain.order.status"]

        # 기존 상태 삭제
        self.tier_status_ids.unlink()

        tiers = self.route_id.tier_ids.sorted("sequence")
        if not tiers:
            return

        # 역순으로 날짜 계산 (최종 납품일부터 역산)
        # 마지막 단계 → 우리회사 납품일 = required_date
        # 그 전 단계 → 마지막 단계에 도착해야 하는 날 = required_date - 마지막단계 리드타임
        tier_dates = {}
        running_date = required_date

        for tier in reversed(list(tiers)):
            # 이 단계가 다음 단계(또는 우리)에 도착해야 하는 날짜
            tier_dates[tier.id] = running_date
            # 이 단계의 시작일 = 도착일 - 리드타임
            running_date = running_date - timedelta(days=tier.leadtime)

        # 순서대로 상태 레코드 생성
        for tier in tiers:
            Status.create({
                "chain_order_id": self.id,
                "tier_id": tier.id,
                "supplier_id": tier.supplier_id.id,
                "expected_date": tier_dates.get(tier.id, required_date),
                "state": "pending",
            })

        # 첫 번째 단계에 자동 알림 발송
        first_status = self.tier_status_ids.sorted("sequence")[:1]
        if first_status:
            first_status.action_notify()


class SupplyChainOrderStatus(models.Model):
    """공급망 발주의 각 단계별 상태"""
    _name = "supply.chain.order.status"
    _description = "공급망 단계별 상태"
    _order = "chain_order_id, sequence"

    chain_order_id = fields.Many2one(
        "supply.chain.order",
        string="공급망 발주",
        required=True,
        ondelete="cascade",
    )
    tier_id = fields.Many2one(
        "supply.chain.tier",
        string="공급 단계",
        required=True,
    )
    sequence = fields.Integer(
        related="tier_id.sequence",
        store=True,
    )
    supplier_id = fields.Many2one(
        "res.partner",
        string="협력사",
        required=True,
    )

    # 날짜
    expected_date = fields.Date(string="예상일")
    actual_date = fields.Date(string="실제일")

    # 상태
    state = fields.Selection(
        [
            ("pending", "대기"),
            ("notified", "알림발송"),
            ("confirmed", "확정"),
            ("shipped", "출하"),
            ("completed", "완료"),
            ("issue", "이슈"),
        ],
        string="상태",
        default="pending",
    )

    issue_note = fields.Text(string="이슈 내용")

    # 다음 단계 정보
    delivers_to = fields.Selection(
        related="tier_id.delivers_to",
    )
    next_supplier_id = fields.Many2one(
        related="tier_id.next_supplier_id",
    )

    def action_notify(self):
        """협력사에게 알림 발송"""
        self.ensure_one()
        # 포탈 알림 생성
        self.env["supplier.portal.notification"].create({
            "partner_id": self.supplier_id.id,
            "notification_type": "supply_chain_notify",
            "purchase_order_id": self.chain_order_id.purchase_order_id.id,
            "message": _(
                "공급망 알림: %s 준비 요청 (납품처: %s, 예상일: %s)"
            ) % (
                self.chain_order_id.product_id.display_name,
                self.next_supplier_id.name if self.next_supplier_id else "우리회사",
                self.expected_date,
            ),
        })
        self.state = "notified"
        return True

    def action_confirm(self):
        """협력사 확정"""
        self.ensure_one()
        self.state = "confirmed"
        return True

    def action_ship(self):
        """출하 처리"""
        self.ensure_one()
        self.state = "shipped"
        self.actual_date = fields.Date.today()
        return True

    def action_complete(self):
        """완료 처리"""
        self.ensure_one()
        self.state = "completed"
        if not self.actual_date:
            self.actual_date = fields.Date.today()
        return True

    def action_report_issue(self):
        """이슈 보고"""
        self.ensure_one()
        self.state = "issue"
        # 관련 발주의 담당자에게 알림
        po = self.chain_order_id.purchase_order_id
        if po.buyer_id:
            self.env["supplier.portal.notification"].create({
                "user_id": po.buyer_id.id,
                "notification_type": "supply_chain_issue",
                "purchase_order_id": po.id,
                "message": _(
                    "공급망 이슈: %s - %s 단계에서 문제 발생"
                ) % (
                    self.chain_order_id.product_id.display_name,
                    self.tier_id.name,
                ),
            })
        return True
