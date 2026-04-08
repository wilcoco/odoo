from odoo import fields, models, tools


class OutsourceDailyChart(models.Model):
    """외주 부품 일별 분석 차트 데이터 (언피벗 SQL View)

    outsource_daily_summary (와이드 포맷)를 언피벗하여
    metric_type별로 한 줄씩 → 그래프에서 4개 라인 동시 표시
    """

    _name = "outsource.daily.chart"
    _description = "외주 부품 일별 차트 데이터"
    _auto = False
    _order = "plan_date, product_id, metric_type"

    planning_run_id = fields.Many2one(
        "outsource.planning.run", string="계획 실행", readonly=True,
    )
    product_id = fields.Many2one(
        "product.product", string="외주 부품", readonly=True,
    )
    plan_date = fields.Date(string="날짜", readonly=True)
    metric_type = fields.Selection(
        [
            ("1_demand", "소요량"),
            ("2_incoming", "입고예정"),
            ("3_stock", "종료 재고"),
            ("4_safety", "안전재고"),
        ],
        string="지표",
        readonly=True,
    )
    value = fields.Float(string="수량", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    s.id * 4 AS id,
                    s.planning_run_id,
                    s.product_id,
                    s.plan_date,
                    '1_demand' AS metric_type,
                    s.demand_qty AS value
                FROM outsource_daily_summary s
                UNION ALL
                SELECT
                    s.id * 4 + 1 AS id,
                    s.planning_run_id,
                    s.product_id,
                    s.plan_date,
                    '2_incoming' AS metric_type,
                    s.incoming_qty AS value
                FROM outsource_daily_summary s
                UNION ALL
                SELECT
                    s.id * 4 + 2 AS id,
                    s.planning_run_id,
                    s.product_id,
                    s.plan_date,
                    '3_stock' AS metric_type,
                    s.stock_end AS value
                FROM outsource_daily_summary s
                UNION ALL
                SELECT
                    s.id * 4 + 3 AS id,
                    s.planning_run_id,
                    s.product_id,
                    s.plan_date,
                    '4_safety' AS metric_type,
                    s.safety_stock_qty AS value
                FROM outsource_daily_summary s
            )
        """ % self._table)
