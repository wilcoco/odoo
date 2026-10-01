from markupsafe import Markup

from odoo import api, fields, models


class CamsOpsSystemCheck(models.Model):
    _name = "cams.ops.system.check"
    _description = "회사 운영 시스템 점검"

    name = fields.Char(default="회사 운영 시스템 점검", required=True)
    checked_at = fields.Datetime(compute="_compute_status")
    installed_custom_modules = fields.Integer(compute="_compute_status", string="설치된 커스텀 모듈")
    disabled_crons = fields.Integer(compute="_compute_status", string="중지된 예약 작업")
    recent_errors = fields.Integer(compute="_compute_status", string="최근 오류 로그")
    state = fields.Selection(
        [("ok", "정상"), ("warning", "확인 필요")],
        compute="_compute_status",
        string="상태",
    )
    details_html = fields.Html(compute="_compute_status", string="점검 상세", sanitize=False)

    @api.depends_context("uid")
    def _compute_status(self):
        Module = self.env["ir.module.module"].sudo()
        Cron = self.env["ir.cron"].sudo()
        Logging = self.env["ir.logging"].sudo()
        prefixes = ("cams_", "escon_", "gh_", "injection_")
        installed = Module.search([("state", "=", "installed")]).filtered(
            lambda module: module.name.startswith(prefixes)
        )
        disabled = Cron.search_count([("active", "=", False)])
        since = fields.Datetime.subtract(fields.Datetime.now(), days=1)
        errors = Logging.search_count([
            ("create_date", ">=", since),
            ("level", "in", ("ERROR", "CRITICAL")),
        ])
        state = "warning" if disabled or errors else "ok"
        details = Markup(
            "<ul>"
            "<li>에스콘 커스텀 모듈: <b>%s개</b></li>"
            "<li>중지된 예약 작업: <b>%s개</b></li>"
            "<li>최근 24시간 오류/치명 로그: <b>%s개</b></li>"
            "</ul>"
        ) % (len(installed), disabled, errors)
        for record in self:
            record.checked_at = fields.Datetime.now()
            record.installed_custom_modules = len(installed)
            record.disabled_crons = disabled
            record.recent_errors = errors
            record.state = state
            record.details_html = details

    def action_refresh(self):
        return {"type": "ir.actions.client", "tag": "reload"}
