from odoo import api, fields, models


class PlanningMaterialRequirement(models.Model):
    """계획 확정 전 검토용 원재료(레진 등) 소요/재고 집계.

    계획 라인의 사출 부품 BOM을 전개하여 원재료별 총 소요량을 계산하고,
    현재 가용 재고와 비교하여 부족 여부를 표시한다.
    """

    _name = "injection.planning.material.requirement"
    _description = "생산계획 원재료 소요/재고"
    _order = "is_short desc, material_id"
    _rec_name = "material_id"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    material_id = fields.Many2one(
        "product.product", string="원재료", required=True, index=True,
    )
    uom_id = fields.Many2one(
        "uom.uom", string="단위", related="material_id.uom_id", readonly=True,
    )
    required_qty = fields.Float(
        string="소요량", help="계획 전체 기간 동안 필요한 원재료 총량 (사출 부품 BOM 전개)",
    )
    available_qty = fields.Float(
        string="현재 재고", help="계획 계산 시점의 가용 재고",
    )
    shortage_qty = fields.Float(
        string="부족 수량", compute="_compute_shortage", store=True,
        help="소요량 - 현재 재고 (양수면 부족)",
    )
    coverage_rate = fields.Float(
        string="충족률 (%)", compute="_compute_shortage", store=True,
        help="현재 재고 / 소요량",
    )
    is_short = fields.Boolean(
        string="재고 부족", compute="_compute_shortage", store=True,
    )
    first_need_date = fields.Date(
        string="최초 소요일", help="이 원재료가 처음 필요한 생산일",
    )
    # ── 검사대기 (표시 전용) ──
    # 검사대기 재고는 Stock 하위가 아니라 **형제 위치**에 있으므로 가용재고에 애초에
    # 들어가지 않는다. 여기서 다시 빼면 이중 차감이다. 그래서 **표시만** 한다 —
    # "곧 풀릴 수도 있는 물량이 이만큼 있다" 는 사실을 계획자가 보게 하려는 것이다.
    # 이 수량으로 재구매 여부를 자동 판단하지 않는다(정책 미결).
    iqc_pending_qty = fields.Float(
        string="검사대기 (가용 아님)", readonly=True,
        help="검사대기 위치에서 아직 실제 해제 이동을 완료하지 않은 수량. "
             "가용재고에 포함되지 않으며 부족 판정·발주 계산에서 빼지도 않는다.",
    )
    iqc_reserved_qty = fields.Float(
        string="검사대기 중 예약", readonly=True,
    )
    # **0 과 '모른다' 는 다른 사실이다.** 검사 모듈이 없거나 권한이 없어 못 읽은 것을
    # 빈칸으로 두면 화면에서는 '검사대기 없음' 과 똑같아 보인다. 그러면 계획자는
    # 대기 중인 물량이 없다고 읽는다. (아스트라 2026-09-11 배정)
    iqc_status = fields.Selection(
        [("counted", "집계됨"), ("unavailable", "조회 불가")],
        string="검사대기 집계", readonly=True, default="unavailable",
        help="'집계됨' 이면 옆의 수량이 실제 집계 결과다(0 이면 정말 없다). "
             "'조회 불가' 면 검사 모듈이 없거나 권한이 없어 읽지 못한 것이다.",
    )
    iqc_status_note = fields.Char(
        string="검사대기 집계 비고", readonly=True,
        help="조회하지 못한 이유.",
    )

    # ── 발주 연동 ──
    ordered_qty = fields.Float(
        string="발주 수량", help="부족분에 대해 생성된 발주 수량",
    )
    purchase_order_id = fields.Many2one(
        "purchase.order", string="발주서", readonly=True,
        help="부족분 자동 발주로 생성된 발주서",
    )
    company_id = fields.Many2one(
        "res.company", related="planning_run_id.company_id",
        store=True, index=True, readonly=True,
        help="계획 실행의 회사를 그대로 따른다. 활성 회사가 아니라 **계획의 회사**여야 "
             "다른 회사 계획의 산출물이 우리 목록에 섞이지 않는다. (PR08)",
    )

    @api.depends("required_qty", "available_qty")
    def _compute_shortage(self):
        for rec in self:
            # [R144 관찰 #11] 여유분은 '부족'이 아니다 — 음수 부족·수만 % 충족률을 표시하지 않는다.
            rec.shortage_qty = max(rec.required_qty - rec.available_qty, 0.0)
            rec.is_short = rec.required_qty > rec.available_qty
            rec.coverage_rate = (
                min(rec.available_qty / rec.required_qty * 100.0, 100.0)
                if rec.required_qty > 0
                else 100.0
            )


class PlanningMaterialDaily(models.Model):
    """원재료 일자별 소요/재고 추이 (차트·검토용).

    계획 라인을 생산일별로 전개하여 원재료별 일일 소요량과
    누적(롤링) 재고를 계산한다. 어느 시점에 재고가 마이너스로
    전환되는지(결품 시점) 확인할 수 있다.
    """

    _name = "injection.planning.material.daily"
    _description = "생산계획 원재료 일별 소요/재고"
    _order = "material_id, plan_date"
    _rec_name = "material_id"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    material_id = fields.Many2one(
        "product.product", string="원재료", required=True, index=True,
    )
    plan_date = fields.Date(string="생산일", required=True, index=True)
    required_qty = fields.Float(string="일일 소요량")
    stock_start = fields.Float(string="시작 재고")
    stock_end = fields.Float(string="종료 재고", help="시작 재고 - 일일 소요량")
    is_short = fields.Boolean(
        string="결품", compute="_compute_short", store=True,
        help="종료 재고가 0 미만이면 결품",
    )
    company_id = fields.Many2one(
        "res.company", related="planning_run_id.company_id",
        store=True, index=True, readonly=True,
        help="계획 실행의 회사를 그대로 따른다. 활성 회사가 아니라 **계획의 회사**여야 "
             "다른 회사 계획의 산출물이 우리 목록에 섞이지 않는다. (PR08)",
    )

    @api.depends("stock_end")
    def _compute_short(self):
        for rec in self:
            rec.is_short = rec.stock_end < 0

