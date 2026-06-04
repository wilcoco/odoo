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
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    @api.depends("required_qty", "available_qty")
    def _compute_shortage(self):
        for rec in self:
            rec.shortage_qty = rec.required_qty - rec.available_qty
            rec.is_short = rec.required_qty > rec.available_qty
            rec.coverage_rate = (
                (rec.available_qty / rec.required_qty * 100.0)
                if rec.required_qty > 0
                else 100.0
            )
