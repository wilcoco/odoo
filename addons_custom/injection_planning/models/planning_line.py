from odoo import api, fields, models


class PlanningLine(models.Model):
    _name = "injection.planning.line"
    _description = "생산계획 상세 라인"
    _order = "plan_date, workcenter_id, sequence"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(string="순서", default=10)
    plan_date = fields.Date(string="생산일", required=True, index=True)

    # ── 배정 ──
    workcenter_id = fields.Many2one(
        "mrp.workcenter", string="사출기", required=True,
    )
    mold_id = fields.Many2one(
        "injection.mold", string="금형", required=True,
    )
    product_id = fields.Many2one(
        "product.product", string="사출 부품", required=True,
    )

    # ── 수량 ──
    demand_qty = fields.Float(string="순수요")
    planned_qty = fields.Float(string="계획 수량", help="불량율 + 초기불량 반영")
    defect_rate = fields.Float(string="적용 불량율 (%)")
    initial_scrap = fields.Integer(string="적용 초기 불량")

    # ── 금형 교체 ──
    changeover_needed = fields.Boolean(string="금형 교체 필요")
    changeover_count = fields.Integer(
        string="교체 횟수",
        compute="_compute_changeover_count", store=True,
        help="금형 교체 필요 시 1, 아니면 0 (피벗 합계용)",
    )
    changeover_hours = fields.Float(string="교체 시간 (h)")

    # ── 시간 ──
    production_hours = fields.Float(
        string="생산 시간 (h)", compute="_compute_hours", store=True,
    )
    total_hours = fields.Float(
        string="총 소요 시간 (h)", compute="_compute_hours", store=True,
    )
    start_time = fields.Datetime(string="시작 예정")
    end_time = fields.Datetime(string="종료 예정")
    shift = fields.Selection(
        [("day", "주간"), ("night", "야간")],
        string="교대",
        help="MO 분할 시 교대 구분",
    )

    # ── 재고 ──
    current_stock = fields.Float(string="현재 재고")
    max_inventory = fields.Float(string="최대 재고")

    # ── MO 연결 ──
    mo_id = fields.Many2one("mrp.production", string="제조 오더", readonly=True)

    state = fields.Selection(
        [("draft", "초안"), ("confirmed", "확정"), ("done", "완료")],
        string="상태",
        default="draft",
    )

    @api.depends("changeover_needed")
    def _compute_changeover_count(self):
        for rec in self:
            rec.changeover_count = 1 if rec.changeover_needed else 0

    @api.depends("planned_qty", "changeover_hours", "changeover_needed")
    def _compute_hours(self):
        for rec in self:
            cap = self.env["injection.machine.mold.capability"].search([
                ("workcenter_id", "=", rec.workcenter_id.id),
                ("mold_id", "=", rec.mold_id.id),
            ], limit=1)
            if cap and cap.hourly_capacity > 0:
                rec.production_hours = rec.planned_qty / cap.hourly_capacity
            else:
                rec.production_hours = 0.0
            co = rec.changeover_hours if rec.changeover_needed else 0.0
            rec.total_hours = rec.production_hours + co
