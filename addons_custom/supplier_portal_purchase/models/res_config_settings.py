from odoo import api, fields, models

from .supplier_demand_forecast import PARAM_HORIZON, DEFAULT_HORIZON

CRON_XMLID = "supplier_portal_purchase.cron_supplier_demand_forecast"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    supplier_forecast_horizon_days = fields.Integer(
        string="소요 전망 기간(일)",
        config_parameter=PARAM_HORIZON,
        default=DEFAULT_HORIZON,
        help="협력사 포탈에 보여줄 소요 전망의 앞으로 며칠 범위")
    supplier_forecast_interval_number = fields.Integer(
        string="갱신 주기 값", default=1,
        help="소요 전망 자동 갱신 주기 (예: 1 + '일' = 매일)")
    supplier_forecast_interval_type = fields.Selection(
        [("hours", "시간"), ("days", "일"), ("weeks", "주")],
        string="갱신 주기 단위", default="days")

    @api.model
    def get_values(self):
        res = super().get_values()
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if cron:
            res.update(
                supplier_forecast_interval_number=cron.interval_number,
                supplier_forecast_interval_type=cron.interval_type,
            )
        return res

    def set_values(self):
        super().set_values()
        cron = self.env.ref(CRON_XMLID, raise_if_not_found=False)
        if cron and self.supplier_forecast_interval_number > 0 \
                and self.supplier_forecast_interval_type:
            cron.sudo().write({
                "interval_number": self.supplier_forecast_interval_number,
                "interval_type": self.supplier_forecast_interval_type,
            })
