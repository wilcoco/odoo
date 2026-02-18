from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # ── IATF 설정 (V8) ──
    iatf_copq_expense_account_id = fields.Many2one(
        "account.account", string="COPQ 비용 계정",
        config_parameter="iatf.copq_expense_account_id",
    )
    iatf_quarantine_location_id = fields.Many2one(
        "stock.location", string="격리 창고 위치",
        config_parameter="iatf.quarantine_location_id",
    )
    iatf_auto_nc_on_fail = fields.Boolean(
        string="검사 불합격 시 NC 자동 생성",
        config_parameter="iatf.auto_nc_on_fail", default=True,
    )
    iatf_auto_hold_on_iqc = fields.Boolean(
        string="IQC 대기 중 로트 자동 보류",
        config_parameter="iatf.auto_hold_on_iqc", default=True,
    )
    iatf_scar_threshold = fields.Integer(
        string="SCAR 자동 발행 NC 건수 임계값",
        config_parameter="iatf.scar_threshold", default=3,
    )
    iatf_nc_closure_days_warning = fields.Integer(
        string="NC 미종결 경고 일수",
        config_parameter="iatf.nc_closure_days_warning", default=30,
    )
    iatf_aql_level = fields.Selection(
        [("I", "Level I (축소)"), ("II", "Level II (일반)"), ("III", "Level III (강화)")],
        string="기본 AQL 검사 수준",
        config_parameter="iatf.aql_level", default="II",
    )
