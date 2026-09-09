from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    ppap_submission_id = fields.Many2one("iatf.ppap.submission", string="PPAP 제출")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._check_first_mo_ppap()
        return records

    def _check_first_mo_ppap(self):
        """신규 제품 첫 MO → PPAP 제출 요청 자동 생성 (L2-19)"""
        if not self.product_id:
            return
        # 해당 제품으로 이전 MO가 있는지 확인
        prev_mo = self.search([
            ("product_id", "=", self.product_id.id),
            ("id", "!=", self.id),
        ], limit=1)
        if prev_mo:
            return  # 첫 MO가 아님

        PPAP = self.env.get("iatf.ppap.submission")
        if PPAP is None:
            return
        # 첫 MO에 따른 자동 요청만 권한 상승. 생산 담당자에게 PPAP 편집권을
        # 부여하지 않으며, 자동 조회·생성은 해당 MO 회사 안에서 수행한다.
        PPAP = PPAP.sudo().with_company(self.company_id)
        # 기존 PPAP가 있는지 확인
        existing = PPAP.search([
            ("company_id", "=", self.company_id.id),
            ("product_id", "=", self.product_id.id),
        ], limit=1)
        if existing:
            return

        ppap = PPAP.create({
            "title": _("초도품 PPAP: %s") % self.product_id.name,
            "product_id": self.product_id.id,
            "submission_level": "3",
            "company_id": self.company_id.id,
        })
        self.ppap_submission_id = ppap.id
        self.message_post(body=_("신규 제품 첫 MO → PPAP 제출 요청 %s 자동 생성됨") % ppap.name)
        _logger.info("PPAP auto-created: %s for first MO %s, product %s",
                     ppap.name, self.name, self.product_id.name)

    def action_view_ppap(self):
        self.ensure_one()
        if self.ppap_submission_id:
            return {
                "type": "ir.actions.act_window",
                "res_model": "iatf.ppap.submission",
                "res_id": self.ppap_submission_id.id,
                "view_mode": "form",
                "target": "current",
            }
