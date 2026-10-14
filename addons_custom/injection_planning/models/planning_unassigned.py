from odoo import fields, models


class PlanningUnassigned(models.Model):
    """배정하지 못한 수요 — P1-PP06.

    설비·금형의 물리 제약을 어기는 배정은 '경고 후 진행' 이 아니라 **차단**한다.
    그런데 차단만 하고 조용히 사라지면 계획자는 그 수요가 빠진 줄 모른다. 그래서
    차단된 수요는 사유와 함께 이 큐에 남긴다. 계획 화면에서 바로 보인다.

    이 원장은 계산 산출물이므로 담당자에게는 읽기만 준다. 기록은 계산 훅 안에서만
    한다(`injection.planning.run._planning_ledger`, P1-PP03).
    """

    _name = "injection.planning.unassigned"
    _description = "미배정 수요"
    _order = "plan_date, product_id, id"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행",
        required=True, ondelete="cascade", index=True,
    )
    product_id = fields.Many2one(
        "product.product", string="사출 부품", required=True,
    )
    plan_date = fields.Date(string="필요일", required=True, index=True)
    qty = fields.Float(string="미배정 수량")
    reason = fields.Selection(
        [
            ("no_capability", "사출기-금형 조합 없음"),
            ("mold_state", "금형 사용 불가(정비중·폐기)"),
            ("clamping", "형체력 부족"),
            ("no_capacity", "계획 기간 가용 가동시간 부족"),
        ],
        string="미배정 사유", required=True,
    )
    detail = fields.Char(string="설명")
    company_id = fields.Many2one(
        related="planning_run_id.company_id", store=True, readonly=True,
    )
