from odoo import fields, models


class PlanningViolation(models.Model):
    """[R135] 계획이 납기·재고 범위를 지키지 못한 곳. 미배정 큐와 별개로 **기록**한다.

    수용 기준 4: 「재고/납기 동시 충족이 불가능하면 위반 종류·부족량·지연·원인을 표시하고
    조용히 정상 확정하지 않는다.」
    """
    _name = "injection.planning.violation"
    _description = "생산계획 위반"
    _order = "plan_date, product_id, id"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="계획 실행", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        "res.company", related="planning_run_id.company_id", store=True, index=True, readonly=True)
    product_id = fields.Many2one("product.product", string="사출 부품", required=True)
    plan_date = fields.Date(string="일자", required=True, index=True)
    kind = fields.Selection([
        ("late", "납기 지연"),
        ("safety_shortfall", "안전재고 부족"),
        ("max_inventory_excess", "최대재고 초과"),
        ("early_production", "조기 생산(납기 준수용)"),
        ("demand_horizon_short", "수요 범위 부족(안전재고 목표 불완전)"),
    ], string="종류", required=True, index=True)
    severity = fields.Selection([
        ("hard", "하드 제약(시간·자원)"), ("policy", "정책 위반(재고 범위)"), ("notice", "안내(허용된 결과)")],
        string="등급", required=True, default="policy",
        help="[R135 검토 #4] 납기 지연·미배정은 하드, 안전·최대재고는 정책, 조기생산은 허용된 연장의 결과라 안내.")
    qty = fields.Float(string="수량")
    days = fields.Integer(string="지연 일수")
    detail = fields.Char(string="원인·설명")
