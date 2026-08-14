from odoo import fields, models, _
from odoo.exceptions import UserError


class PumuiMakeInvoice(models.TransientModel):
    """품의서 → 청구서 생성 (단계 선택: 전체/계약금/중도금/잔금 — 리포트 #6)."""
    _name = "pumui.make.invoice"
    _description = "품의서 청구서 생성"

    pumui_id = fields.Many2one("pumui.request", string="품의서", required=True)
    stage = fields.Selection(
        [("all", "전체 잔여 항목"), ("down", "계약금"), ("interim", "중도금"), ("balance", "잔금"),
         ("normal", "일반")],
        string="청구 단계", default="all", required=True)

    def action_confirm(self):
        self.ensure_one()
        stage = False if self.stage == "all" else self.stage
        if stage and not self.pumui_id._get_invoiceable_lines(stage=stage):
            raise UserError(_("해당 단계(%s)의 미청구 항목이 없습니다.")
                            % dict(self._fields["stage"].selection).get(self.stage))
        return self.pumui_id.action_create_invoice(stage=stage)
