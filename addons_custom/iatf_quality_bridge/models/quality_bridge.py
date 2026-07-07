from odoo import fields, models, _
from odoo.exceptions import UserError


class IatfNonconformity(models.Model):
    _inherit = "iatf.nonconformity"

    quality_alert_id = fields.Many2one(
        "quality.alert", string="품질 경보 (Quality Alert)", copy=False,
        help="이 부적합과 연결된 Odoo 현장 품질경보 (G2 브리지)",
    )

    def _open_quality_alert(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "quality.alert",
            "res_id": self.quality_alert_id.id, "view_mode": "form", "target": "current",
        }

    def action_create_quality_alert(self):
        """IATF 부적합 → 현장 품질경보(quality.alert) 동기 생성·연결."""
        self.ensure_one()
        if self.quality_alert_id:
            return self._open_quality_alert()
        team = self.env["quality.alert.team"].search([], limit=1)
        if not team:
            raise UserError(_("품질경보 팀(quality.alert.team)이 없습니다. 품질 설정에서 먼저 구성하세요."))
        alert = self.env["quality.alert"].create({
            "title": self.title or self.name,
            "description": self.problem_description or "",
            "product_id": self.product_id.id if self.product_id else False,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "partner_id": self.partner_id.id if self.partner_id else False,
            "team_id": team.id,
        })
        self.quality_alert_id = alert.id
        alert.iatf_nonconformity_id = self.id
        self.message_post(body=_("품질경보 %s 생성·연결됨") % (alert.name or alert.title))
        return self._open_quality_alert()


class QualityAlert(models.Model):
    _inherit = "quality.alert"

    iatf_nonconformity_id = fields.Many2one(
        "iatf.nonconformity", string="IATF 부적합", copy=False,
        help="이 품질경보에서 승격된 IATF 부적합 (G2 브리지)",
    )

    def _open_nonconformity(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "iatf.nonconformity",
            "res_id": self.iatf_nonconformity_id.id, "view_mode": "form", "target": "current",
        }

    def action_promote_to_nonconformity(self):
        """현장 품질경보 → IATF 부적합 승격·연결."""
        self.ensure_one()
        if self.iatf_nonconformity_id:
            return self._open_nonconformity()
        nc = self.env["iatf.nonconformity"].create({
            "title": self.title or (self.name and str(self.name)) or _("품질경보 승격"),
            "nc_type": "internal",
            "severity": "major",
            "detection_date": fields.Date.today(),
            "problem_description": self.description or "",
            "product_id": self.product_id.id if self.product_id else False,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "partner_id": self.partner_id.id if self.partner_id else False,
        })
        self.iatf_nonconformity_id = nc.id
        nc.quality_alert_id = self.id
        self.message_post(body=_("IATF 부적합 %s 로 승격됨") % nc.name)
        return self._open_nonconformity()
